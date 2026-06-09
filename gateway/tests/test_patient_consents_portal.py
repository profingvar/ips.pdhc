"""Tests for the patient-portal consent-management surface — IPS Renov 4
(ticket #200).

Auth shape under TestingConfig (AUTH_DISABLED=True):
``require_patient`` reads the ``X-Dev-Patient-Guid`` header — we
pass a known PatientIndex guid to bind each request to a patient.

Coverage:
- GET happy + active filter
- POST grant happy, duplicate-active 409, validation errors
- POST revoke happy, double-revoke 409, cross-patient revoke 404
- granted_via locked to "portal"; granted_by_user_guid = patient
- Audit row shape: actor_type='patient', actor_guid=patient_guid,
  detail.mechanism='consent'
- Auth: missing header → 401
"""
from __future__ import annotations

import uuid

import pytest

from app.models.base import db
from app.models.audit_log import AuditLog
from app.models.fhir_resource import FhirResource
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed(client, db):
    """Two patients (A + B) so cross-patient guards can be tested."""
    fhir_a = FhirResource(
        resource_type="Patient",
        resource_id=str(uuid.uuid4()),
        resource_json={"resourceType": "Patient"},
    )
    fhir_b = FhirResource(
        resource_type="Patient",
        resource_id=str(uuid.uuid4()),
        resource_json={"resourceType": "Patient"},
    )
    db.session.add_all([fhir_a, fhir_b])
    db.session.flush()

    patient_a = PatientIndex(
        fhir_resource_guid=fhir_a.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Andersson",
        given_name="Anna",
    )
    patient_b = PatientIndex(
        fhir_resource_guid=fhir_b.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Bengtsson",
        given_name="Bo",
    )
    db.session.add_all([patient_a, patient_b])
    db.session.commit()

    return {"patient_a": patient_a, "patient_b": patient_b}


def _as_patient(guid):
    return {"X-Dev-Patient-Guid": str(guid)}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_missing_dev_header_returns_401(client, seed):
    resp = client.get("/api/v1/patient/consents")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET — list own consents
# ---------------------------------------------------------------------------

def test_list_empty(client, seed):
    resp = client.get(
        "/api/v1/patient/consents",
        headers=_as_patient(seed["patient_a"].guid),
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"items": [], "total": 0}


def test_list_returns_own_consents_only(client, seed):
    a, b = seed["patient_a"], seed["patient_b"]
    grantee = uuid.uuid4()
    db.session.add(PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=grantee,
        granted_via="portal",
        granted_by_user_guid=a.guid,
    ))
    db.session.add(PatientConsent(
        patient_guid=b.guid,
        grantee_caregiver_guid=grantee,
        granted_via="portal",
        granted_by_user_guid=b.guid,
    ))
    db.session.commit()

    resp = client.get(
        "/api/v1/patient/consents",
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 1
    assert body["items"][0]["patient_guid"] == str(a.guid)


def test_active_filter_off_returns_revoked_too(client, seed):
    from app.models.base import utcnow as _utcnow
    a = seed["patient_a"]
    revoked = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
        revoked_at=_utcnow(),
        revoked_by_user_guid=a.guid,
    )
    active = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add_all([revoked, active])
    db.session.commit()

    r1 = client.get(
        "/api/v1/patient/consents?active=true",
        headers=_as_patient(a.guid),
    )
    assert r1.get_json()["total"] == 1

    r2 = client.get(
        "/api/v1/patient/consents?active=false",
        headers=_as_patient(a.guid),
    )
    assert r2.get_json()["total"] == 2


# ---------------------------------------------------------------------------
# POST — grant
# ---------------------------------------------------------------------------

def test_grant_happy(client, seed):
    a = seed["patient_a"]
    grantee = uuid.uuid4()

    resp = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(grantee),
            "granted_note": "for the diabetes clinic",
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["patient_guid"] == str(a.guid)
    assert body["grantee_caregiver_guid"] == str(grantee)
    assert body["granted_via"] == "portal"
    assert body["granted_by_user_guid"] == str(a.guid)
    assert body["is_active"] is True
    assert body["consented_concept_guids"] is None


def test_grant_with_concept_narrowing(client, seed):
    a = seed["patient_a"]
    grantee = uuid.uuid4()
    c1, c2 = str(uuid.uuid4()), str(uuid.uuid4())

    resp = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(grantee),
            "consented_concept_guids": [c1, c2],
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201
    assert set(resp.get_json()["consented_concept_guids"]) == {c1, c2}


def test_grant_with_expires_at(client, seed):
    a = seed["patient_a"]
    resp = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(uuid.uuid4()),
            "expires_at": "2099-01-01T00:00:00Z",
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201
    assert resp.get_json()["expires_at"].startswith("2099-01-01")


def test_grant_duplicate_active_returns_409(client, seed):
    a = seed["patient_a"]
    grantee = uuid.uuid4()
    db.session.add(PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=grantee,
        granted_via="portal",
        granted_by_user_guid=a.guid,
    ))
    db.session.commit()

    resp = client.post(
        "/api/v1/patient/consents",
        json={"grantee_caregiver_guid": str(grantee)},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 409
    assert "existing_consent_guid" in resp.get_json()


def test_grant_missing_grantee_returns_400(client, seed):
    a = seed["patient_a"]
    resp = client.post(
        "/api/v1/patient/consents",
        json={},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 400


def test_grant_invalid_grantee_returns_400(client, seed):
    a = seed["patient_a"]
    resp = client.post(
        "/api/v1/patient/consents",
        json={"grantee_caregiver_guid": "not-a-uuid"},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 400


def test_grant_ignores_caller_supplied_granted_via(client, seed):
    """Even if the caller passes granted_via='in_person', we lock it
    to 'portal' (the patient is on the patient portal by definition).
    """
    a = seed["patient_a"]
    resp = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(uuid.uuid4()),
            "granted_via": "in_person",  # ignored
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201
    assert resp.get_json()["granted_via"] == "portal"


def test_grant_concept_guids_validation(client, seed):
    a = seed["patient_a"]

    # Wrong type
    r1 = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(uuid.uuid4()),
            "consented_concept_guids": "not-a-list",
        },
        headers=_as_patient(a.guid),
    )
    assert r1.status_code == 400

    # Empty list
    r2 = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(uuid.uuid4()),
            "consented_concept_guids": [],
        },
        headers=_as_patient(a.guid),
    )
    assert r2.status_code == 400

    # Bad UUID
    r3 = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(uuid.uuid4()),
            "consented_concept_guids": ["not-a-uuid"],
        },
        headers=_as_patient(a.guid),
    )
    assert r3.status_code == 400


# ---------------------------------------------------------------------------
# POST /<consent_guid>/revoke
# ---------------------------------------------------------------------------

def test_revoke_own_consent_happy(client, seed):
    a = seed["patient_a"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    cg = consent.guid

    resp = client.post(
        f"/api/v1/patient/consents/{cg}/revoke",
        json={"reason": "changed my mind"},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["is_active"] is False
    assert body["revoked_reason"] == "changed my mind"
    assert body["revoked_by_user_guid"] == str(a.guid)


def test_cannot_revoke_other_patients_consent(client, seed):
    """Confused-deputy guard: B cannot revoke A's consent, and the
    response must look identical to 'no such consent'."""
    a, b = seed["patient_a"], seed["patient_b"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    cg = consent.guid

    resp = client.post(
        f"/api/v1/patient/consents/{cg}/revoke",
        json={},
        headers=_as_patient(b.guid),
    )
    assert resp.status_code == 404


def test_double_revoke_returns_409(client, seed):
    a = seed["patient_a"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    cg = consent.guid

    r1 = client.post(
        f"/api/v1/patient/consents/{cg}/revoke",
        json={},
        headers=_as_patient(a.guid),
    )
    assert r1.status_code == 200

    r2 = client.post(
        f"/api/v1/patient/consents/{cg}/revoke",
        json={},
        headers=_as_patient(a.guid),
    )
    assert r2.status_code == 409


def test_revoke_unknown_consent_returns_404(client, seed):
    a = seed["patient_a"]
    resp = client.post(
        f"/api/v1/patient/consents/{uuid.uuid4()}/revoke",
        json={},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Audit shape
# ---------------------------------------------------------------------------

def test_audit_row_carries_patient_actor_and_consent_mechanism(client, seed):
    a = seed["patient_a"]
    grantee = uuid.uuid4()

    resp = client.post(
        "/api/v1/patient/consents",
        json={
            "grantee_caregiver_guid": str(grantee),
            "granted_note": "test",
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201
    consent_guid = resp.get_json()["guid"]

    row = (
        db.session.query(AuditLog)
        .filter(AuditLog.event_type == "consent.granted",
                AuditLog.resource_guid == uuid.UUID(consent_guid))
        .one()
    )
    assert row.actor_type == "patient"
    assert str(row.actor_guid) == str(a.guid)
    assert str(row.patient_guid) == str(a.guid)
    assert row.resource_type == "PatientConsent"
    assert row.detail["mechanism"] == "consent"
    assert row.detail["grantee_caregiver_guid"] == str(grantee)


def test_revoke_audit_row(client, seed):
    a = seed["patient_a"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    cg = consent.guid

    client.post(
        f"/api/v1/patient/consents/{cg}/revoke",
        json={"reason": "test-revoke"},
        headers=_as_patient(a.guid),
    )

    row = (
        db.session.query(AuditLog)
        .filter(AuditLog.event_type == "consent.revoked",
                AuditLog.resource_guid == cg)
        .one()
    )
    assert row.actor_type == "patient"
    assert str(row.actor_guid) == str(a.guid)
    assert row.detail["reason"] == "test-revoke"
