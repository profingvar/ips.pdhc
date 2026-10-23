"""The BULK care-access filter — the care twin of /patients/analysis-filter.

Why it exists: the composed zone rule was reachable only one patient at a time
(`/care-access-check`), so a consumer building a patient LIST of 300 faced 300
round trips. The predictable result was consumers scoping lists themselves, and
icd11.pdhc did exactly that — matching on care_unit alone, which is Zone 1
applied unconditionally, so a patient in a sibling vårdenhet was invisible even
with no spärr at all.

`care_access_policy` is explicit: "no two consumers may enforce different zone
rules." This endpoint is what makes that affordable.
"""
import uuid

import pytest

from app.models import FhirResource, PatientBlock, PatientIndex
from app.models.clinic import Clinic
from app.models.patient_index import PatientClinicAssignment

ORG_A = str(uuid.uuid4())        # vårdgivare A
UNIT_A1 = str(uuid.uuid4())      # vårdenhet under A — the reader's
UNIT_A2 = str(uuid.uuid4())      # sibling vårdenhet under A
ORG_B = str(uuid.uuid4())


def _patient(db, family="Svensson"):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid,
                     resource_id=str(uuid.uuid4()),
                     family_name=family, given_name="S")
    db.session.add(p)
    db.session.flush()
    return p


def _clinic(db, unit_guid, caregiver_guid, name="Enhet"):
    c = Clinic(name=name, organisation_guid=unit_guid,
               care_organisation_guid=caregiver_guid, is_active=True)
    db.session.add(c)
    db.session.flush()
    return c


def _assign(db, patient, clinic):
    db.session.add(PatientClinicAssignment(patient_guid=patient.guid,
                                           clinic_guid=clinic.guid))
    db.session.commit()


def _filter(client, guids, unit=UNIT_A1, org=ORG_A):
    return client.post("/api/v1/patients/care-access-filter",
                       json={"patient_guids": [str(g) for g in guids],
                             "reader_care_unit_guid": unit,
                             "reader_care_organisation_guid": org})


# =======================================================================
# the operator's rule
# =======================================================================

def test_a_sibling_unit_under_the_SAME_vardgivare_is_ALLOWED(client, db):
    """Zone 2: no spärr, so the whole vårdgivare sees the patient."""
    p = _patient(db)
    _assign(db, p, _clinic(db, UNIT_A2, ORG_A, "Systerenhet"))
    r = _filter(client, [p.guid])
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    body = r.get_json()
    assert [a["patient_guid"] for a in body["allowed"]] == [str(p.guid)]
    assert body["excluded"] == []


def test_an_INRE_SPARR_narrows_it_to_the_patients_own_unit(client, db):
    """The other half of the operator's rule: with a spärr, the sibling unit
    stops seeing them."""
    p = _patient(db)
    _assign(db, p, _clinic(db, UNIT_A2, ORG_A, "Systerenhet"))
    db.session.add(PatientBlock(patient_guid=p.guid, source_scope_type="clinic",
                                source_scope_id=UNIT_A2))
    db.session.commit()
    body = _filter(client, [p.guid]).get_json()
    assert body["allowed"] == []
    assert body["excluded"][0]["patient_guid"] == str(p.guid)
    assert body["excluded"][0]["reason"] == "inre_sparr"


def test_the_patients_OWN_unit_is_never_hidden_from_itself(client, db):
    """Zone 1. A spärr on the unit does not blind the unit that authored it."""
    p = _patient(db)
    _assign(db, p, _clinic(db, UNIT_A1, ORG_A, "Min enhet"))
    db.session.add(PatientBlock(patient_guid=p.guid, source_scope_type="clinic",
                                source_scope_id=UNIT_A1))
    db.session.commit()
    body = _filter(client, [p.guid]).get_json()
    assert [a["patient_guid"] for a in body["allowed"]] == [str(p.guid)]
    assert body["allowed"][0]["zone"] == 1


def test_a_different_vardgivare_needs_consent(client, db):
    """Zone 3, no consent -> excluded."""
    p = _patient(db)
    _assign(db, p, _clinic(db, UNIT_A2, ORG_A))
    body = _filter(client, [p.guid], unit=str(uuid.uuid4()), org=ORG_B).get_json()
    assert body["allowed"] == []
    assert body["excluded"][0]["reason"] == "no_sharing_consent"


# =======================================================================
# it fails safe
# =======================================================================

def test_an_unknown_patient_is_EXCLUDED_not_allowed(client, db):
    """A typo must not widen a list."""
    body = _filter(client, [str(uuid.uuid4())]).get_json()
    assert body["allowed"] == []
    assert body["excluded"][0]["reason"] == "unknown_patient"


def test_a_patient_with_no_clinic_assignment_is_excluded(client, db):
    """No care relationship to evaluate — the policy module requires unknown
    inputs to take the safe value."""
    p = _patient(db)
    db.session.commit()
    body = _filter(client, [p.guid]).get_json()
    assert body["allowed"] == []
    assert body["excluded"][0]["reason"] == "no_clinic_assignment"


def test_a_missing_reader_unit_is_refused(client, db):
    r = client.post("/api/v1/patients/care-access-filter",
                    json={"patient_guids": []})
    assert r.status_code == 400


def test_the_batch_is_capped(client, db):
    r = _filter(client, [str(uuid.uuid4()) for _ in range(501)])
    assert r.status_code == 400
    assert "500" in r.get_json()["error"]


def test_an_empty_list_is_fine(client, db):
    body = _filter(client, []).get_json()
    assert body["allowed"] == [] and body["excluded"] == []


def test_mixed_patients_are_split_correctly(client, db):
    """The shape consumers actually use: some allowed, some not, reasons given."""
    ok = _patient(db, "Allowed")
    _assign(db, ok, _clinic(db, UNIT_A2, ORG_A, "Syster"))
    blocked = _patient(db, "Blocked")
    bc = _clinic(db, str(uuid.uuid4()), ORG_A, "Spärrad enhet")
    _assign(db, blocked, bc)
    db.session.add(PatientBlock(patient_guid=blocked.guid, source_scope_type="clinic",
                                source_scope_id=str(bc.organisation_guid)))
    db.session.commit()
    body = _filter(client, [ok.guid, blocked.guid]).get_json()
    assert [a["patient_guid"] for a in body["allowed"]] == [str(ok.guid)]
    assert [e["patient_guid"] for e in body["excluded"]] == [str(blocked.guid)]
