"""#793 — the three euIPS REQUIRED sections may never be empty.

The guideline: *"you must state 'no known allergies' rather than leave the
section empty."* Measured in production 2026-10-07 by the shipped #791 code,
110 of 150 patients had NO statement in any section — 110 invalid summaries.

These go through the real generator endpoint. The single most important test is
`test_every_generated_patient_is_conformant`: the guarantee is "always", so a
sample of one proves nothing and the test generates a batch.
"""
from __future__ import annotations

import uuid

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_sections as euips
from app.services import euips_required as req


def _clinic(db):
    c = Clinic(name="Required Test Clinic", organisation_guid="org-req-0001",
               identifier="org-req-0001", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _generate(client, clinic, n, skip=False):
    data = {"clinic_guid": str(clinic.guid), "count": str(n)}
    if skip:
        data["skip_clinical"] = "on"
    resp = client.post("/admin/mock-data", data=data, follow_redirects=True)
    assert resp.status_code == 200
    return resp


def _status(patient):
    rows = (_db.session.query(FhirResource)
            .filter(FhirResource.patient_guid == patient.guid).all())
    return euips.status_for_resources(rows)


class TestTheGuaranteeIsAlways:
    def test_every_generated_patient_is_conformant(self, client, db):
        """A batch, not a sample: "always" is the claim being tested."""
        c = _clinic(db)
        _generate(client, c, 30)
        patients = _db.session.query(PatientIndex).all()
        assert len(patients) >= 30
        bad = []
        for p in patients:
            st = _status(p)
            if not euips.is_conformant(st):
                bad.append((str(p.guid), {k: st[k] for k in euips.REQUIRED_KEYS}))
        assert bad == [], f"{len(bad)} non-conformant, e.g. {bad[:3]}"

    def test_no_required_section_is_ever_MISSING(self, client, db):
        c = _clinic(db)
        _generate(client, c, 30)
        for p in _db.session.query(PatientIndex).all():
            st = _status(p)
            for key in euips.REQUIRED_KEYS:
                assert st[key] != euips.MISSING, f"{key} MISSING for {p.guid}"

    def test_skip_clinical_is_still_conformant(self, client, db):
        """THE decision #793 asked for. skip_clinical exists so sim.pdhc can
        own the clinical data without two sources of truth -- a good reason,
        and not a reason to create an invalid summary meanwhile. It emits the
        three absent assertions rather than skipping the sections."""
        c = _clinic(db)
        _generate(client, c, 15, skip=True)
        for p in _db.session.query(PatientIndex).all():
            st = _status(p)
            assert euips.is_conformant(st), {k: st[k] for k in euips.REQUIRED_KEYS}
            for key in euips.REQUIRED_KEYS:
                assert st[key] == euips.EXPLICITLY_ABSENT

    def test_skip_clinical_still_skips_the_OPTIONAL_content(self, client, db):
        """It must remain a real skip, or its purpose is lost -- sim would be
        overwriting generated observations, the two-sources-of-truth problem
        it exists to avoid."""
        c = _clinic(db)
        _generate(client, c, 10, skip=True)
        for p in _db.session.query(PatientIndex).all():
            st = _status(p)
            assert st["immunisations"] == euips.MISSING
            assert st["vital_signs"] == euips.MISSING
            assert st["procedures"] == euips.MISSING


class TestBothPathsAreExercised:
    def test_a_batch_produces_some_content_and_some_absent(self, client, db):
        """If every patient took one branch the other would be untested in
        practice. 40 patients at the configured rates makes both near-certain.
        """
        c = _clinic(db)
        _generate(client, c, 40)
        seen = {k: set() for k in euips.REQUIRED_KEYS}
        for p in _db.session.query(PatientIndex).all():
            st = _status(p)
            for k in euips.REQUIRED_KEYS:
                seen[k].add(st[k])
        assert euips.EXPLICITLY_ABSENT in seen["allergies"], seen
        assert euips.PRESENT in seen["problems"], seen

    def test_the_absent_rates_are_all_strictly_between_0_and_1(self):
        """A rate of 0 or 1 would silently make one branch dead code."""
        for key, rate in req.ABSENT_RATE.items():
            assert 0 < rate < 1, f"{key}={rate} makes a branch unreachable"
        assert set(req.ABSENT_RATE) == set(euips.REQUIRED_KEYS)


class TestTheHybridFormat:
    def test_every_required_resource_carries_narrative(self, client, db):
        """euIPS is explicitly hybrid and the guideline calls the narrative the
        safety net -- "what a clinician abroad sees". A coded-only entry
        satisfies a validator and fails the purpose."""
        c = _clinic(db)
        _generate(client, c, 10)
        types = {"AllergyIntolerance", "Condition", "MedicationStatement"}
        rows = (_db.session.query(FhirResource)
                .filter(FhirResource.resource_type.in_(types)).all())
        assert rows
        for r in rows:
            txt = (r.resource_json or {}).get("text")
            assert isinstance(txt, dict), f"{r.resource_type} has no narrative"
            assert txt.get("status")
            assert "xhtml" in (txt.get("div") or ""), txt

    def test_an_absent_assertion_says_so_in_words_too(self, client, db):
        c = _clinic(db)
        _generate(client, c, 15, skip=True)
        rows = (_db.session.query(FhirResource)
                .filter(FhirResource.resource_type == "AllergyIntolerance").all())
        assert rows
        assert any("No known allergies" in (r.resource_json["text"]["div"])
                   for r in rows)


class TestActiveVersusPast:
    def test_the_problem_list_contains_only_active_conditions(self, client, db):
        """problems and past_illnesses share Condition and are separated ONLY
        by clinicalStatus, so a resolved condition emitted here would land in
        the active problem list."""
        c = _clinic(db)
        _generate(client, c, 20)
        rows = (_db.session.query(FhirResource)
                .filter(FhirResource.resource_type == "Condition").all())
        assert rows
        for r in rows:
            codings = (r.resource_json.get("clinicalStatus") or {}).get("coding") or []
            codes = {cd.get("code") for cd in codings}
            assert codes == {"active"}, f"{codes} in the active problem list"


class TestNoDuplicateGeneration:
    def test_the_required_sections_are_generated_once_not_twice(self, client, db):
        """They were moved out of _mock_patient_resources. If that removal had
        been missed, each patient would get two sets."""
        c = _clinic(db)
        _generate(client, c, 1)
        p = _db.session.query(PatientIndex).first()
        rows = (_db.session.query(FhirResource)
                .filter(FhirResource.patient_guid == p.guid).all())
        allergies = [r for r in rows if r.resource_type == "AllergyIntolerance"]
        # At most 2 real allergies, or exactly 1 absent assertion.
        assert 1 <= len(allergies) <= 2, len(allergies)
        absent = [r for r in allergies if euips.is_absent_assertion(r.resource_json)]
        assert len(absent) <= 1
        if absent:
            assert len(allergies) == 1, "an absent assertion alongside content"


class TestTheAbsentDetectionCoversTheRealFieldName:
    def test_a_medications_absent_assertion_is_detected(self, client, db):
        """#791's first version checked only `code` and
        `medicationCodeableConcept`, while this codebase writes `medication` --
        all 119 pre-existing rows use it. So a medications absent assertion was
        undetectable, silently turning EXPLICITLY_ABSENT back into MISSING for
        a REQUIRED section. Found by starting #793.
        """
        body = {"resourceType": "MedicationStatement",
                "medication": euips.absent_coding("medications")}
        assert euips.is_absent_assertion(body) is True

    def test_a_real_medication_is_not_mistaken_for_an_absence(self):
        body = {"resourceType": "MedicationStatement",
                "medication": {"coding": [
                    {"system": "http://www.whocc.no/atc", "code": "A10BA02"}]}}
        assert euips.is_absent_assertion(body) is False

    def test_the_generator_and_the_detector_agree_on_the_field(self, client, db):
        """The two must use the same key or the guarantee is cosmetic."""
        c = _clinic(db)
        _generate(client, c, 12, skip=True)
        rows = (_db.session.query(FhirResource)
                .filter(FhirResource.resource_type == "MedicationStatement").all())
        assert rows
        assert all(euips.is_absent_assertion(r.resource_json) for r in rows)
