"""#1040: GET /patients/<guid>/clinics decides access for its callers
(request's need-to-know, sso's patient link). An ENDED assignment must not
count, and the answer names the platform guid, because the route also resolves
a FHIR resource_id."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment


@pytest.fixture
def world(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir); db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     family_name="Synthetic", given_name="Test")
    now, left = (Clinic(name=f"now {uuid.uuid4().hex[:6]}", is_active=True),
                 Clinic(name=f"left {uuid.uuid4().hex[:6]}", is_active=True))
    db.session.add_all([p, now, left]); db.session.flush()
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=now.guid))
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=left.guid,
                                           ended_at=datetime.now(timezone.utc)))
    db.session.commit()
    return p, now, left


def test_an_ended_assignment_is_not_listed(client, world):
    p, now, left = world
    r = client.get(f"/api/v1/patients/{p.guid}/clinics")
    assert r.status_code == 200
    assert [c["guid"] for c in r.get_json()] == [str(now.guid)]


def test_the_answer_names_the_platform_guid_also_for_a_resource_id(client, world):
    p, _, _ = world
    for ident in (str(p.guid), p.resource_id):
        r = client.get(f"/api/v1/patients/{ident}/clinics")
        assert r.status_code == 200
        assert r.headers.get("X-PDHC-Patient-Guid") == str(p.guid)
