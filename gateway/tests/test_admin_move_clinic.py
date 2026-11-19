"""Byt klinik (2026-11-19): the admin patient page ends one clinic assignment
and opens another in ONE transaction, through patient_assignment."""
import uuid

import pytest

from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex


@pytest.fixture
def seed(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir); db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     family_name="Flyttsson", given_name="Test")
    old = Clinic(name="Gamla", organisation_guid=str(uuid.uuid4()), is_active=True)
    new = Clinic(name="Nya", organisation_guid=str(uuid.uuid4()), is_active=True)
    db.session.add_all([p, old, new]); db.session.flush()
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=old.guid))
    db.session.commit()
    with client.session_transaction() as s:
        s["sso_user"] = {"is_su_admin": True, "user_type": "professional"}
    return p, old, new


def _open(db, p):
    return sorted(c.name for a, c in PatientClinicAssignment.active_only(
        db.session.query(PatientClinicAssignment, Clinic)
        .join(Clinic, Clinic.guid == PatientClinicAssignment.clinic_guid)
        .filter(PatientClinicAssignment.patient_guid == p.guid)).all())


def test_page_offers_the_button(client, seed):
    p, old, new = seed
    body = client.get(f"/admin/patients/{p.guid}").get_data(as_text=True)
    assert "Byt klinik" in body and str(new.guid) in body and "Gamla" in body


def test_move_ends_old_opens_new_and_audits_both(client, db, seed):
    p, old, new = seed
    r = client.post(f"/admin/patients/{p.guid}/move-clinic",
                    data={"from_clinic_guid": str(old.guid), "to_clinic_guid": str(new.guid)})
    assert r.status_code == 302
    assert _open(db, p) == ["Nya"]
    ended = db.session.query(PatientClinicAssignment).filter_by(
        patient_guid=p.guid, clinic_guid=old.guid).one()
    assert ended.ended_at is not None                      # kept, not deleted
    events = {e.event_type for e in db.session.query(AuditLog).filter_by(patient_guid=p.guid)}
    assert {"patient.assignment_ended", "patient.assigned"} <= events


def test_a_refused_second_half_rolls_back_the_first(client, db, seed):
    p, old, new = seed
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=new.guid))
    db.session.commit()                                    # already open at "Nya"
    client.post(f"/admin/patients/{p.guid}/move-clinic",
                data={"from_clinic_guid": str(old.guid), "to_clinic_guid": str(new.guid)})
    db.session.expire_all()
    assert _open(db, p) == ["Gamla", "Nya"]                # old NOT ended


def test_same_clinic_and_garbage_are_refused(client, db, seed):
    p, old, new = seed
    for data in ({"from_clinic_guid": str(old.guid), "to_clinic_guid": str(old.guid)},
                 {"from_clinic_guid": "x", "to_clinic_guid": str(new.guid)}):
        client.post(f"/admin/patients/{p.guid}/move-clinic", data=data)
    assert _open(db, p) == ["Gamla"]


def test_without_su_or_clinic_staff_nothing_moves(client, db, seed):
    p, old, new = seed
    with client.session_transaction() as s:
        s["sso_user"] = {"is_su_admin": False, "user_type": "professional"}
    client.post(f"/admin/patients/{p.guid}/move-clinic",
                data={"from_clinic_guid": str(old.guid), "to_clinic_guid": str(new.guid)})
    db.session.expire_all()
    assert _open(db, p) == ["Gamla"]
