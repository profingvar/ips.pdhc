"""#791 — the euIPS section model: where content lives, and absent vs missing.

The decision implemented here: section content is `fhir_resources` rows, an
explicitly-absent section is a real resource carrying the IPS absent/unknown
code, and section status is COMPUTED rather than stored.

The tests that matter are the three-state ones. Before this, "no row" conflated
"the clinician recorded nothing to report" with "the simulator never generated
it", and 110 of 150 live patients were in the second state while looking like
the first.
"""
from __future__ import annotations

import uuid

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_sections as euips


def _patient(db, batch=None):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     family_name="Section", given_name="Test",
                     generation_batch_guid=batch)
    db.session.add(p)
    db.session.commit()
    res.patient_guid = p.guid
    db.session.commit()
    return p


def _add(db, patient, rtype, code_json=None):
    rid = str(uuid.uuid4())
    body = {"resourceType": rtype, "id": rid}
    if code_json is not None:
        body["code"] = code_json
    r = FhirResource(resource_type=rtype, resource_id=rid,
                     resource_json=body, patient_guid=patient.guid)
    db.session.add(r)
    db.session.commit()
    return r


class TestTheCatalogueMatchesTheDocument:
    def test_the_obligation_levels_and_counts(self):
        from collections import Counter
        c = Counter(s.obligation for s in euips.SECTIONS)
        assert c == {"required": 3, "recommended": 4,
                     "optional": 7, "eu_addition": 3}

    def test_the_three_required_sections_are_the_documents_three(self):
        assert euips.REQUIRED_KEYS == ("allergies", "problems", "medications")

    def test_every_section_key_is_unique(self):
        keys = [s.key for s in euips.SECTIONS]
        assert len(keys) == len(set(keys))

    def test_the_codes_are_flagged_as_unverified(self):
        """The plan forbids invented terminology and forbids a conformance
        claim. The flag is how that stays true rather than being forgotten."""
        assert euips.CODES_VERIFIED is False

    def test_no_absent_code_is_invented_where_ips_defines_none(self):
        """The EU additions have no established IPS absent code, so they must
        carry None rather than a plausible-looking guess."""
        for key in ("alerts", "travel_history", "patient_provided"):
            assert euips.BY_KEY[key].absent_code is None
            assert euips.absent_coding(key) is None


class TestTheThreeStates:
    def test_a_real_entry_is_PRESENT(self, client, db):
        p = _patient(db)
        _add(db, p, "AllergyIntolerance",
             {"coding": [{"system": "http://snomed.info/sct", "code": "91936005"}]})
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert st["allergies"] == euips.PRESENT

    def test_an_absent_assertion_is_EXPLICITLY_ABSENT_not_missing(self, client, db):
        """'No known allergies' is a clinical statement, not an empty section.
        This is the distinction the whole decision exists for."""
        p = _patient(db)
        _add(db, p, "AllergyIntolerance", euips.absent_coding("allergies"))
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert st["allergies"] == euips.EXPLICITLY_ABSENT

    def test_nothing_at_all_is_MISSING(self, client, db):
        p = _patient(db)
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert st["allergies"] == euips.MISSING
        assert st["problems"] == euips.MISSING
        assert st["medications"] == euips.MISSING

    def test_real_content_beats_a_stale_absent_assertion(self, client, db):
        """A patient can carry both: 'no known allergies' recorded earlier, and
        a real allergy recorded later. The data must win, or the summary hides
        a genuine allergy behind stale bookkeeping -- a safety question, not a
        presentation one."""
        p = _patient(db)
        _add(db, p, "AllergyIntolerance", euips.absent_coding("allergies"))
        _add(db, p, "AllergyIntolerance",
             {"coding": [{"system": "http://snomed.info/sct", "code": "91936005"}]})
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert st["allergies"] == euips.PRESENT


class TestConformance:
    def test_absent_assertions_alone_are_conformant(self, client, db):
        """A patient with nothing to report is a VALID summary, provided each
        required section says so explicitly."""
        p = _patient(db)
        _add(db, p, "AllergyIntolerance", euips.absent_coding("allergies"))
        _add(db, p, "Condition", euips.absent_coding("problems"))
        _add(db, p, "MedicationStatement", euips.absent_coding("medications"))
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert euips.is_conformant(st) is True

    def test_two_of_three_is_not_conformant(self, client, db):
        p = _patient(db)
        _add(db, p, "AllergyIntolerance", euips.absent_coding("allergies"))
        _add(db, p, "Condition", euips.absent_coding("problems"))
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert euips.is_conformant(st) is False

    def test_an_empty_patient_is_not_conformant(self, client, db):
        """The live state of 110 of 150 patients."""
        p = _patient(db)
        st = euips.status_for_resources([])
        assert euips.is_conformant(st) is False

    def test_recommended_sections_do_not_affect_conformance(self, client, db):
        """Only the three required ones do -- that is what 'required' means."""
        p = _patient(db)
        for key, rtype in (("allergies", "AllergyIntolerance"),
                           ("problems", "Condition"),
                           ("medications", "MedicationStatement")):
            _add(db, p, rtype, euips.absent_coding(key))
        st = euips.status_for_resources(
            _db.session.query(FhirResource).filter_by(patient_guid=p.guid).all())
        assert st["devices"] == euips.MISSING
        assert euips.is_conformant(st) is True


class TestTheEndpoint:
    def test_it_reports_every_section(self, client, db):
        p = _patient(db)
        body = client.get(f"/api/v1/patients/{p.guid}/euips-sections").get_json()
        assert len(body["sections"]) == len(euips.SECTIONS)
        assert body["conformant"] is False
        assert set(body["required_sections_missing"]) == set(euips.REQUIRED_KEYS)

    def test_it_says_the_codes_are_unverified_in_the_response(self, client, db):
        """Not buried in a docstring. A caller must not read `conformant` as an
        EU conformance claim, so the response says so itself."""
        p = _patient(db)
        body = client.get(f"/api/v1/patients/{p.guid}/euips-sections").get_json()
        assert body["codes_verified"] is False
        assert "NOT a claim of EU/EHDS conformance" in body["disclaimer"]

    def test_a_malformed_guid_is_400_not_500(self, client, db):
        """#730's lesson: PatientIndex.guid is a real Postgres uuid column, so
        an unparseable guid reaching the query raised at the driver and
        fail-closed an entire cohort while blaming the wrong service."""
        resp = client.get("/api/v1/patients/not-a-uuid/euips-sections")
        assert resp.status_code == 400

    def test_an_unknown_patient_is_404(self, client, db):
        resp = client.get(f"/api/v1/patients/{uuid.uuid4()}/euips-sections")
        assert resp.status_code == 404

    def test_it_surfaces_the_batch_guid(self, client, db):
        batch = uuid.uuid4()
        p = _patient(db, batch=batch)
        body = client.get(f"/api/v1/patients/{p.guid}/euips-sections").get_json()
        assert body["generation_batch_guid"] == str(batch)


class TestTheBatchColumnIsAdditive:
    def test_an_existing_row_may_have_none(self, client, db):
        """The 150 live rows stay NULL, which correctly means 'not from a
        tracked batch'. A NOT NULL column would have required a backfill."""
        p = _patient(db)
        assert p.generation_batch_guid is None

    def test_to_dict_keeps_every_key_consumers_already_read(self, client, db):
        """sim.pdhc reads this dict via GET /api/v1/clinics/<guid>/patients.
        The addition must not displace anything."""
        p = _patient(db)
        d = p.to_dict()
        for key in ("guid", "identifier_system", "identifier_value",
                    "family_name", "given_name", "birth_date", "gender",
                    "is_active"):
            assert key in d, f"{key} disappeared from to_dict()"
        assert d["generation_batch_guid"] is None
