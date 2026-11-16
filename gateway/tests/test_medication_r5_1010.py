"""#1010 — ips writes MedicationStatement in R5.

`medication` is a CodeableReference in R5, so the coding belongs under
`medication.concept`; ips wrote a bare CodeableConcept there. And R5's
medication-statement-status valueset is recorded | entered-in-error | draft,
while ips wrote "active" (and "unknown" for no-known-medications).

Driven through the real entry points: the mock-data generator (which builds the
euIPS required sections) and the admin add-resource form. The 322 rows written
before this keep their old shape on purpose -- every reader reads both -- so the
read side is asserted for both shapes too.
"""
from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_sections as euips
from app.services import euips_summary
from tests.test_required_sections_793 import _clinic, _generate

R5_STATUS = {"recorded", "entered-in-error", "draft"}


def _meds():
    return [r.resource_json for r in _db.session.query(FhirResource)
            .filter(FhirResource.resource_type == "MedicationStatement").all()]


def test_generated_medications_are_R5(client, db):
    _generate(client, _clinic(db), 20)
    meds = _meds()
    assert meds, "the generator wrote no MedicationStatement"
    for m in meds:
        assert m["status"] in R5_STATUS, m["status"]
        assert set(m["medication"]) == {"concept"}, "a bare CodeableConcept is not R5"
        assert m["medication"]["concept"].get("coding")
        assert "medicationCodeableConcept" not in m


def test_no_known_medications_is_still_recognised_as_absent(client, db):
    """The absence is carried by the code, so moving it under `concept` and
    dropping status "unknown" must not turn EXPLICITLY_ABSENT into MISSING."""
    _generate(client, _clinic(db), 30)
    absent = [m for m in _meds() if euips.is_absent_assertion(m)]
    assert absent, "no no-known-medications assertion among 30 patients"
    assert all(m["status"] == "recorded" for m in absent)


def test_the_admin_form_writes_R5(client, db):
    _generate(client, _clinic(db), 1, skip=True)
    p = _db.session.query(PatientIndex).first()
    r = client.post(f"/admin/patients/{p.guid}/add-resource", data={
        "resource_type": "MedicationStatement", "code_text": "metformin",
        "code_system": "http://www.whocc.no/atc", "code_value": "A10BA02"})
    assert r.status_code in (302, 200)
    m, = [x for x in _meds() if "A10BA02" in str(x.get("medication"))]
    assert m["status"] == "recorded"
    assert m["medication"] == {"concept": {
        "coding": [{"system": "http://www.whocc.no/atc", "code": "A10BA02", "display": "metformin"}],
        "text": "metformin"}}


class _Row:
    def __init__(self, rj):
        self.resource_type, self.resource_json, self.resource_id = "MedicationStatement", rj, "x"


def test_the_summary_reads_the_OLD_and_the_NEW_shape_alike():
    cc = {"coding": [{"system": "http://www.whocc.no/atc", "code": "A10BA02", "display": "metformin"}]}
    old = euips_summary.entry(_Row({"resourceType": "MedicationStatement", "status": "active", "medication": cc}))
    new = euips_summary.entry(_Row({"resourceType": "MedicationStatement", "status": "recorded",
                                    "medication": {"concept": cc}}))
    assert (old["code"], old["display"]) == (new["code"], new["display"]) == ("A10BA02", "metformin")
