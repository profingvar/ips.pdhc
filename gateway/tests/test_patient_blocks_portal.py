"""Tests for the patient-portal block-management surface — IPS Renov 3
(ticket #199).

Auth shape under TestingConfig (AUTH_DISABLED=True):
``require_patient`` consults the ``X-Dev-Patient-Guid`` header — we
pass a known PatientIndex guid to bind each request to a specific
patient identity. No SSO mock needed.

Coverage:
- GET happy + active filter
- POST create happy + duplicate active 409 + validation 400/404
- POST lift happy + already-lifted 409 + wrong-patient 404
  (confused-deputy)
- POST extend happy + extend_by_seconds + lifted-block 409 + past
  expiry 400 + mutually-exclusive payload 400
- Audit row shape: actor_type='patient', actor_guid=patient_guid,
  detail.mechanism='consent'
- Auth: missing header → 401; wrong patient_guid (other patient's
  block) → 404
"""
from __future__ import annotations

import uuid

import pytest

from app.models.base import db
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed(client, db):
    """Two patients (A + B), two clinics; clinic_a will be the block
    target. Patient B exists so we can check the cross-patient guard.
    """
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
    db.session.flush()

    clinic_a = Clinic(name="Cardiology A", is_active=True)
    clinic_b = Clinic(name="Endocrinology B", is_active=True)
    db.session.add_all([clinic_a, clinic_b])
    db.session.commit()

    return {
        "patient_a": patient_a,
        "patient_b": patient_b,
        "clinic_a": clinic_a,
        "clinic_b": clinic_b,
    }


def _as_patient(guid):
    return {"X-Dev-Patient-Guid": str(guid)}


# ---------------------------------------------------------------------------
# Auth — require_patient
# ---------------------------------------------------------------------------

def test_missing_dev_header_returns_401(client, seed):
    """In AUTH_DISABLED dev mode the X-Dev-Patient-Guid header is
    mandatory. (In prod the equivalent is the Bearer-token check.)"""
    resp = client.get("/api/v1/patient/blocks")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["resourceType"] == "OperationOutcome"


def test_missing_bearer_in_prod_path_blocked_at_require_patient(client, seed, app):
    """Sanity-check the require_patient decorator's prod branch by
    flipping AUTH_DISABLED OFF for a single call. Without a Bearer
    token, the decorator must return 401."""
    app.config["AUTH_DISABLED"] = False
    try:
        resp = client.get("/api/v1/patient/blocks")
    finally:
        app.config["AUTH_DISABLED"] = True
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET — list own blocks
# ---------------------------------------------------------------------------

def test_list_empty(client, seed):
    resp = client.get(
        "/api/v1/patient/blocks",
        headers=_as_patient(seed["patient_a"].guid),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"items": [], "total": 0}


def test_list_returns_own_blocks_only(client, seed):
    a, b = seed["patient_a"], seed["patient_b"]
    clinic_a = seed["clinic_a"]
    db.session.add(PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    ))
    db.session.add(PatientBlock(
        patient_guid=b.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=b.guid,
    ))
    db.session.commit()

    resp = client.get(
        "/api/v1/patient/blocks",
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 1
    assert body["items"][0]["patient_guid"] == str(a.guid)
    # Patient sees her own scope details unredacted.
    assert body["items"][0]["source_scope_name"] == "Cardiology A"


# ---------------------------------------------------------------------------
# POST — create
# ---------------------------------------------------------------------------

def test_create_happy(client, seed):
    a = seed["patient_a"]
    clinic_a = seed["clinic_a"]
    resp = client.post(
        "/api/v1/patient/blocks",
        json={
            "source_scope_type": "clinic",
            "source_scope_id": str(clinic_a.guid),
            "reason": "privacy",
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["patient_guid"] == str(a.guid)
    assert body["source_scope_id"] == str(clinic_a.guid)
    assert body["is_active"] is True

    # Persisted with patient as the creator
    row = db.session.query(PatientBlock).filter_by(guid=body["guid"]).one()
    assert str(row.created_by_user_guid) == str(a.guid)
    assert row.created_reason == "privacy"


def test_create_with_expires_at(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    resp = client.post(
        "/api/v1/patient/blocks",
        json={
            "source_scope_type": "clinic",
            "source_scope_id": str(clinic_a.guid),
            "expires_at": "2099-01-01T00:00:00Z",
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201
    assert resp.get_json()["expires_at"].startswith("2099-01-01")


def test_create_duplicate_active_returns_409(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    db.session.add(PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    ))
    db.session.commit()

    resp = client.post(
        "/api/v1/patient/blocks",
        json={
            "source_scope_type": "clinic",
            "source_scope_id": str(clinic_a.guid),
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert "existing_block_guid" in body


def test_create_unknown_clinic_returns_404(client, seed):
    a = seed["patient_a"]
    resp = client.post(
        "/api/v1/patient/blocks",
        json={
            "source_scope_type": "clinic",
            "source_scope_id": str(uuid.uuid4()),
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 404


def test_create_invalid_scope_type_returns_400(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    resp = client.post(
        "/api/v1/patient/blocks",
        json={
            "source_scope_type": "something-bogus",
            "source_scope_id": str(clinic_a.guid),
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /<block_guid>/lift
# ---------------------------------------------------------------------------

def test_lift_own_block_records_consent(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/lift",
        json={"reason": "I want to share again"},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["lift_kind"] == "consent"
    assert body["is_active"] is False
    assert body["lifted_reason"] == "I want to share again"
    # No mechanical filter — this is a consent lift, not indispensable
    assert body["lift_concept_guids"] is None
    assert body["lift_expires_at"] is None


def test_cannot_lift_other_patients_block(client, seed):
    """Confused-deputy guard: patient B cannot lift patient A's block,
    and the response must not distinguish 'wrong patient' from
    'no such block' (would leak block existence)."""
    a, b, clinic_a = seed["patient_a"], seed["patient_b"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/lift",
        json={"reason": "trying to lift someone else's"},
        headers=_as_patient(b.guid),
    )
    assert resp.status_code == 404


def test_double_lift_returns_409(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    # First lift — happy
    r1 = client.post(
        f"/api/v1/patient/blocks/{bg}/lift",
        json={},
        headers=_as_patient(a.guid),
    )
    assert r1.status_code == 200

    # Second lift — already-lifted 409
    r2 = client.post(
        f"/api/v1/patient/blocks/{bg}/lift",
        json={},
        headers=_as_patient(a.guid),
    )
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# POST /<block_guid>/extend
# ---------------------------------------------------------------------------

def test_extend_by_seconds_pushes_expires_forward(client, seed):
    from datetime import datetime, timezone, timedelta

    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    near = datetime.now(timezone.utc) + timedelta(hours=1)
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
        expires_at=near,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/extend",
        json={"extend_by_seconds": 7 * 24 * 3600},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 200, resp.get_json()
    new_expires = resp.get_json()["expires_at"]
    assert new_expires is not None
    # The anchor was `near` (1h from now); +7d should land >6d from now.
    parsed = datetime.fromisoformat(new_expires.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    assert parsed > datetime.now(timezone.utc) + timedelta(days=6)


def test_extend_with_absolute_expires_at(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/extend",
        json={"expires_at": "2099-12-31T00:00:00Z"},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 200
    assert resp.get_json()["expires_at"].startswith("2099-12-31")


def test_extend_with_both_payloads_rejected(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/extend",
        json={"expires_at": "2099-12-31T00:00:00Z", "extend_by_seconds": 60},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 400


def test_extend_past_expiry_rejected(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/extend",
        json={"expires_at": "2000-01-01T00:00:00Z"},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 400


def test_cannot_extend_lifted_block(client, seed):
    from app.models.base import utcnow as _utcnow
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_a.guid,
        created_by_user_guid=a.guid,
        lifted_at=_utcnow(),
        lifted_by_user_guid=a.guid,
        lift_kind="consent",
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    resp = client.post(
        f"/api/v1/patient/blocks/{bg}/extend",
        json={"extend_by_seconds": 3600},
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Audit shape — actor=patient + mechanism=consent
# ---------------------------------------------------------------------------

def test_audit_row_carries_patient_actor_and_consent_mechanism(client, seed):
    a, clinic_a = seed["patient_a"], seed["clinic_a"]
    resp = client.post(
        "/api/v1/patient/blocks",
        json={
            "source_scope_type": "clinic",
            "source_scope_id": str(clinic_a.guid),
            "reason": "p",
        },
        headers=_as_patient(a.guid),
    )
    assert resp.status_code == 201
    block_guid = resp.get_json()["guid"]

    row = (
        db.session.query(AuditLog)
        .filter(AuditLog.event_type == "block.created",
                AuditLog.resource_guid == uuid.UUID(block_guid))
        .one()
    )
    assert row.actor_type == "patient"
    assert str(row.actor_guid) == str(a.guid)
    assert str(row.patient_guid) == str(a.guid)
    assert row.detail["mechanism"] == "consent"
    assert row.detail["source_scope_id"] == str(clinic_a.guid)
