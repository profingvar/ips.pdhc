"""#796 — the three EU-specific euIPS sections.

Medical alerts; travel history; patient-provided information.

The test that matters most is the provenance one. Measured before writing the
code: **no Flag resource exists anywhere on the platform** — zero in ips, and
nothing in request.pdhc, cdr.pdhc or gateway.pdhc emits one. So these are the
platform's first Flags and the simulator sets the convention.

That is an MDR question, not a tidiness one. plan.pdhc authors thresholds (out
of scope); request.pdhc applies them and alerts (in scope, likely Rule 11). If
that path later emits computed alerts as Flags and the simulated ones carry no
provenance, the ambiguity is created retroactively and test data that looks
clinical pollutes the evidence for a technical file.
"""
from __future__ import annotations

import random

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.services import euips_eu_additions as eu
from app.services import euips_optional as opt
from app.services import euips_sections as euips


def _clinic(db):
    c = Clinic(name="EU Test Clinic", organisation_guid="org-eu-0001",
               identifier="org-eu-0001", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _generate(client, clinic, n):
    resp = client.post("/admin/mock-data",
                       data={"clinic_guid": str(clinic.guid), "count": str(n)},
                       follow_redirects=True)
    assert resp.status_code == 200


class Row:
    def __init__(self, t, j):
        self.resource_type, self.resource_json = t, j


class TestSimulatedAlertsAreMarked:
    def test_every_flag_carries_the_simulated_provenance_tag(self, client, db):
        """The MDR-relevant invariant. These are the platform's first Flags."""
        _generate(client, _clinic(db), 50)
        flags = (_db.session.query(FhirResource)
                 .filter(FhirResource.resource_type == "Flag").all())
        assert flags, "no Flag generated in 50 patients"
        for f in flags:
            assert eu.is_simulated(f.resource_json), f.resource_json

    def test_the_tag_is_at_resource_level_so_it_survives_extraction(self):
        """In `meta`, not in the narrative only: a resource read out of a
        bundle, a search result or an export must still carry it."""
        body = eu._alerts("Patient/p", random.Random(1))[0]
        assert body["meta"]["tag"][0]["system"] == eu.PROVENANCE_SYSTEM
        assert body["meta"]["tag"][0]["code"] == eu.SIMULATED

    def test_the_narrative_also_says_simulated(self):
        """Belt and braces: a clinician reading the human-readable text sees
        it without inspecting meta."""
        body = eu._alerts("Patient/p", random.Random(1))[0]
        assert "SIMULATED" in body["text"]["div"]

    def test_an_unmarked_resource_is_not_reported_as_simulated(self):
        """The read side must not default to 'simulated' -- that would make a
        genuinely computed alert look like test data, which is the error in the
        other direction."""
        assert eu.is_simulated({"resourceType": "Flag"}) is False
        assert eu.is_simulated(None) is False
        assert eu.is_simulated({"meta": {"tag": [{"system": "other",
                                                  "code": "simulated"}]}}) is False

    def test_an_alert_is_clinically_weighted_not_decorative(self):
        """The section exists so a clinician abroad sees these first."""
        codes = {a[0] for a in eu._ALERTS}
        assert len(codes) >= 3
        for _, display, note in eu._ALERTS:
            assert display and note


class TestTravelHistory:
    def test_it_is_attributed_to_its_own_section_only(self):
        """Travel carries the social-history CATEGORY, so a category-only rule
        made it mark `social_history` too."""
        body = eu._travel_history("Patient/p", random.Random(1))[0]
        present = [k for k, v in
                   euips.status_for_resources([Row("Observation", body)]).items()
                   if v == euips.PRESENT]
        assert present == ["travel_history"], present

    def test_the_code_is_the_provisional_one_and_is_flagged(self):
        """#795 left TRAVEL_CODES empty rather than guess. #796 settles it
        provisionally, and CODES_VERIFIED must still be False -- the choice is
        recorded, not asserted as verified."""
        assert euips.TRAVEL_CODES == frozenset({"420008001"})
        assert euips.CODES_VERIFIED is False

    def test_travel_is_a_period_not_an_instant(self):
        """"When did you travel" is a window, and the window is what relates
        it to an illness -- which is why the section exists at all."""
        body = eu._travel_history("Patient/p", random.Random(1))[0]
        p = body["effectivePeriod"]
        assert p["start"] < p["end"], p

    def test_travel_dates_are_in_the_past(self):
        from datetime import date
        rng = random.Random(2)
        today = date.today().isoformat()
        for _ in range(200):
            body = eu._travel_history("Patient/p", rng)[0]
            assert body["effectivePeriod"]["start"][:10] <= today


class TestPatientProvidedInformation:
    def test_the_performer_is_the_subject(self):
        """THE discriminator. Without it the resource is an ordinary
        clinician-recorded observation and the section means nothing."""
        body = eu._patient_provided("Patient/p", random.Random(1))[0]
        assert body["performer"][0]["reference"] == body["subject"]["reference"]

    def test_it_is_attributed_to_its_own_section_only(self):
        """It carries the `survey` category, which functional status also uses,
        so a category-only rule marked both."""
        body = eu._patient_provided("Patient/p", random.Random(1))[0]
        present = [k for k, v in
                   euips.status_for_resources([Row("Observation", body)]).items()
                   if v == euips.PRESENT]
        assert present == ["patient_provided"], present

    def test_a_clinician_recorded_survey_is_functional_status_not_patient_provided(self):
        """The subtraction must cut the right way: the same survey recorded by
        a clinician belongs to functional status."""
        body = opt._functional_status("Patient/p", "1970-05-05", random.Random(1))[0]
        assert "performer" not in body
        present = [k for k, v in
                   euips.status_for_resources([Row("Observation", body)]).items()
                   if v == euips.PRESENT]
        assert present == ["functional_status"], present


class TestNoSectionSwallowsAnother:
    def test_every_observation_belongs_to_exactly_one_section(self):
        """Six sections map to Observation and are told apart by category,
        code and provenance. A resource matching two of them means one section
        is silently claiming another's content -- which happened three times
        while this ticket was being written."""
        rng = random.Random(7)
        samples = [
            ("vital sign", opt._vital_signs("Patient/p", "1970-05-05", rng)[0]),
            ("social history", opt._social_history("Patient/p", "1970-05-05", rng)[0]),
            ("functional status", opt._functional_status("Patient/p", "1970-05-05", rng)[0]),
            ("travel", eu._travel_history("Patient/p", rng)[0]),
            ("patient-provided", eu._patient_provided("Patient/p", rng)[0]),
        ]
        for _ in range(80):
            pr = opt._pregnancy("Patient/p", "1990-05-05", "female", rng)
            if pr:
                samples.append(("pregnancy", pr[0]))
                break
        for label, body in samples:
            present = [k for k, v in
                       euips.status_for_resources(
                           [Row(body["resourceType"], body)]).items()
                       if v == euips.PRESENT]
            assert len(present) == 1, f"{label} -> {present}"

    def test_conformance_is_untouched_by_the_eu_additions(self, client, db):
        _generate(client, _clinic(db), 25)
        from app.models.patient_index import PatientIndex
        for p in _db.session.query(PatientIndex).all():
            rows = (_db.session.query(FhirResource)
                    .filter(FhirResource.patient_guid == p.guid).all())
            st = euips.status_for_resources(rows)
            assert euips.is_conformant(st), {k: st[k] for k in euips.REQUIRED_KEYS}
