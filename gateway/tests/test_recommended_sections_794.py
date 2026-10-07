"""#794 — the four euIPS RECOMMENDED sections.

Immunisations; procedures; medical devices and implants; diagnostic results.

Three things measured in production drove this, and each has a test:

* **Medical devices did not exist.** No Device or DeviceUseStatement resource
  type had ever been written. One of the four recommended sections was simply
  absent from the simulator.
* **Diagnostic reports linked to nothing.** All 61 live rows carried
  `code`/`status`/`conclusion` and NO `result`, so the results — the part a
  clinician reads — were not there.
* **Immunisation dates were generation time.** 97 rows across 40 distinct
  dates, every one the moment its batch ran, so an 80-year-old's childhood
  vaccine was dated today.

And the distinction from #793: a recommended section may legitimately be
absent. All three outcomes — content, explicit absence, nothing — are valid,
and #799 must not report a MISSING recommended section as a failure.
"""
from __future__ import annotations

import random
from datetime import date

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_recommended as rec
from app.services import euips_sections as euips

RECOMMENDED = ("immunisations", "procedures", "devices", "diagnostic_results")


def _clinic(db):
    c = Clinic(name="Rec Test Clinic", organisation_guid="org-rec-0001",
               identifier="org-rec-0001", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _generate(client, clinic, n):
    resp = client.post("/admin/mock-data",
                       data={"clinic_guid": str(clinic.guid), "count": str(n)},
                       follow_redirects=True)
    assert resp.status_code == 200


def _rows(rtype=None):
    q = _db.session.query(FhirResource)
    if rtype:
        q = q.filter(FhirResource.resource_type == rtype)
    return q.all()


class TestMedicalDevicesNowExist:
    def test_device_resources_are_generated(self, client, db):
        """The section that was entirely absent. 40 patients, because the
        presence rate is deliberately low (devices are uncommon)."""
        _generate(client, _clinic(db), 40)
        assert _rows("Device"), "no Device resource was generated at all"

    def test_a_device_has_a_use_statement_pointing_at_it(self, client, db):
        _generate(client, _clinic(db), 40)
        devices = {r.resource_json["id"] for r in _rows("Device")}
        uses = _rows("DeviceUseStatement")
        assert uses, "Device without any DeviceUseStatement"
        for u in uses:
            target = u.resource_json["device"]["reference"].split("/")[1]
            assert target in devices, f"DeviceUseStatement -> missing {target}"

    def test_the_cgm_sensor_is_in_the_vocabulary(self):
        """cgm.pdhc is a live provider on this platform, so the simulator and
        the real integration should describe the same object."""
        displays = [d[1].lower() for d in rec._DEVICES]
        assert any("glucose monitoring" in d for d in displays), displays


class TestDiagnosticReportsCarryResults:
    def test_a_lab_report_references_its_observations(self, client, db):
        """The measured gap: all 61 live rows had no `result`."""
        _generate(client, _clinic(db), 20)
        labs = [r for r in _rows("DiagnosticReport")
                if "result" in r.resource_json]
        assert labs, "no DiagnosticReport carries a result list"
        obs_ids = {r.resource_json["id"] for r in _rows("Observation")}
        for rep in labs:
            refs = rep.resource_json["result"]
            assert refs, "empty result list"
            for ref in refs:
                oid = ref["reference"].split("/")[1]
                assert oid in obs_ids, f"dangling result reference {oid}"

    def test_lab_observations_carry_ucum_units(self, client, db):
        """The guideline requires UCUM for units."""
        _generate(client, _clinic(db), 20)
        lab_obs = [r for r in _rows("Observation")
                   if any(c.get("code") == "laboratory"
                          for cat in (r.resource_json.get("category") or [])
                          for c in (cat.get("coding") or []))]
        assert lab_obs, "no laboratory-category observations"
        for o in lab_obs:
            q = o.resource_json["valueQuantity"]
            assert q["system"] == "http://unitsofmeasure.org", q
            assert q.get("unit")

    def test_an_imaging_report_may_have_a_conclusion_and_no_result(self, client, db):
        """Correct for imaging, unlike a lab panel -- which is why the two are
        built from separate lists rather than forced into one shape."""
        _generate(client, _clinic(db), 40)
        reports = _rows("DiagnosticReport")
        assert reports
        for rep in reports:
            j = rep.resource_json
            assert ("result" in j) or j.get("conclusion"), \
                "a report with neither results nor a conclusion says nothing"


class TestImmunisationDatesFollowTheBirthDate:
    def test_no_immunisation_predates_birth_or_lies_in_the_future(self, client, db):
        _generate(client, _clinic(db), 30)
        today = date.today().isoformat()
        for p in _db.session.query(PatientIndex).all():
            if not p.birth_date:
                continue
            birth = p.birth_date.isoformat()
            for r in (_db.session.query(FhirResource)
                      .filter(FhirResource.patient_guid == p.guid,
                              FhirResource.resource_type == "Immunization")
                      .all()):
                when = r.resource_json.get("occurrenceDateTime", "")[:10]
                if not when:
                    continue
                if euips.is_absent_assertion(r.resource_json):
                    continue        # an absent assertion has no real occurrence
                assert when >= birth, f"immunisation {when} before birth {birth}"
                assert when <= today, f"immunisation {when} in the future"

    def test_dates_are_not_all_the_same_moment(self, client, db):
        """The live defect: 97 rows across 40 distinct dates, each the moment
        its batch ran. One batch here must produce many distinct dates."""
        _generate(client, _clinic(db), 25)
        dates = {r.resource_json.get("occurrenceDateTime", "")[:10]
                 for r in _rows("Immunization")
                 if not euips.is_absent_assertion(r.resource_json)}
        dates.discard("")
        assert len(dates) > 5, f"only {len(dates)} distinct dates: {sorted(dates)[:5]}"

    def test_a_child_does_not_get_an_adult_only_vaccine(self):
        rng = random.Random(9)
        bodies = rec.recommended_sections_for("Patient/p", "2022-01-01", rng=rng)
        for b in bodies:
            if b["resourceType"] == "Immunization":
                disp = (b.get("vaccineCode") or {}).get("text", "").lower()
                assert "influenza" not in disp, disp


class TestRecommendedMayBeAbsent:
    def test_all_three_outcomes_occur(self, client, db):
        """The distinction from #793. A recommended section may be content, an
        explicit absence, or nothing -- and #799 must not call the third a
        failure."""
        rng = random.Random(5)
        seen = {k: set() for k in RECOMMENDED}

        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j

        for _ in range(200):
            birth = f"{rng.randint(1935, 2020)}-05-14"
            bodies = rec.recommended_sections_for("Patient/p", birth, rng=rng)
            st = euips.status_for_resources(
                [Row(b["resourceType"], b) for b in bodies])
            for k in RECOMMENDED:
                seen[k].add(st[k])
        for k in ("immunisations", "procedures", "devices"):
            assert seen[k] == {euips.PRESENT, euips.EXPLICITLY_ABSENT,
                               euips.MISSING}, (k, seen[k])
        # diagnostic_results has no IPS absent code, so only two outcomes.
        assert seen["diagnostic_results"] == {euips.PRESENT, euips.MISSING}, \
            seen["diagnostic_results"]

    def test_a_missing_recommended_section_does_not_break_conformance(self, client, db):
        """Only the three REQUIRED sections decide conformance."""
        _generate(client, _clinic(db), 25)
        for p in _db.session.query(PatientIndex).all():
            rows = (_db.session.query(FhirResource)
                    .filter(FhirResource.patient_guid == p.guid).all())
            st = euips.status_for_resources(rows)
            assert euips.is_conformant(st), {k: st[k] for k in euips.REQUIRED_KEYS}

    def test_the_presence_rates_leave_every_branch_reachable(self):
        for key, rate in rec.PRESENCE_RATE.items():
            assert 0 < rate < 1, f"{key}={rate} makes a branch dead code"
        assert set(rec.PRESENCE_RATE) == set(RECOMMENDED)
        assert 0 < rec.ABSENT_SHARE < 1


class TestStructuralValidity:
    def test_the_immunisation_absent_assertion_has_an_occurrence(self, client, db):
        """FHIR makes Immunization.occurrence[x] required (1..1), so omitting
        it on an absent assertion produces an invalid resource. Caught by a
        probe, not by a validator -- there is no FHIR validator in this test
        path, which is why this is pinned explicitly."""
        rng = random.Random(1)
        found = False
        for _ in range(200):
            for b in rec.recommended_sections_for("Patient/p", "1950-01-01", rng=rng):
                if b["resourceType"] == "Immunization" and \
                        euips.is_absent_assertion(b):
                    found = True
                    assert "occurrenceDateTime" in b, b
        assert found, "never generated an immunisation absent assertion"

    def test_every_resource_carries_narrative(self, client, db):
        _generate(client, _clinic(db), 15)
        for rtype in ("Immunization", "Procedure", "Device",
                      "DeviceUseStatement", "DiagnosticReport"):
            for r in _rows(rtype):
                txt = (r.resource_json or {}).get("text")
                assert isinstance(txt, dict) and "xhtml" in (txt.get("div") or ""), \
                    f"{rtype} has no narrative"
