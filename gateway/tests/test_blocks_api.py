"""Tests for the PatientBlock REST surface — spärr Phase 1 (#197).

Covers:
- Create (5.1) — happy, duplicate active 409, scope validation, 404
- List (5.2) — admin sees all, staff sees own clinic's details +
  redaction for others, unrelated staff 403
- Lift (5.3) — consent path, indispensable_care happy +
  mechanical-filter requirement (legal 2026-06-04), invalid kind
- Metadata (5.4) — count + indispensable-care flag, no relationship
  needed
- Audit — block.created / block.lifted rows shape

The TestingConfig sets AUTH_DISABLED=True, which loads a synthetic
admin via _synthetic_dev_user. To test non-admin paths we
monkeypatch that helper to return a real DB User with the right
role + clinic relationship.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.base import db
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed(client, db):
    """Seed minimal world: 2 clinics, 1 patient assigned to clinic A,
    1 staff at clinic A, 1 staff at clinic B (unrelated)."""
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()

    patient = PatientIndex(
        fhir_resource_guid=fhir.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Andersson",
        given_name="Anna",
    )
    db.session.add(patient)
    db.session.flush()

    clinic_a = Clinic(name="Cardiology A", is_active=True)
    clinic_b = Clinic(name="Endocrinology B", is_active=True)
    db.session.add_all([clinic_a, clinic_b])
    db.session.flush()

    db.session.add(PatientClinicAssignment(
        patient_guid=patient.guid, clinic_guid=clinic_a.guid
    ))

    staff_a = User(
        username=f"staff_a_{uuid.uuid4().hex[:8]}",
        display_name="Staff at A",
        role="operator",
        is_active=True,
        is_superuser=False,
    )
    staff_b = User(
        username=f"staff_b_{uuid.uuid4().hex[:8]}",
        display_name="Staff at B",
        role="operator",
        is_active=True,
        is_superuser=False,
    )
    su = User(
        username=f"su_{uuid.uuid4().hex[:8]}",
        display_name="SU",
        role="admin",
        is_active=True,
        is_superuser=True,
    )
    db.session.add_all([staff_a, staff_b, su])
    db.session.flush()

    db.session.add(UserClinicAssignment(
        user_guid=staff_a.guid, clinic_guid=clinic_a.guid
    ))
    db.session.add(UserClinicAssignment(
        user_guid=staff_b.guid, clinic_guid=clinic_b.guid
    ))
    db.session.commit()

    return {
        "patient": patient,
        "clinic_a": clinic_a,
        "clinic_b": clinic_b,
        "staff_a": staff_a,
        "staff_b": staff_b,
        "su": su,
    }


@pytest.fixture
def as_user():
    """Yield a helper that re-points the AUTH_DISABLED synthetic user
    to a real DB user, so non-admin paths can be exercised."""
    @contextmanager
    def _impersonate(user):
        with patch(
            "app.services.auth_service._synthetic_dev_user",
            return_value=user,
        ):
            yield
    return _impersonate


# Python's contextlib is the standard, but importing late keeps the
# fixture body self-contained.
from contextlib import contextmanager  # noqa: E402


# ---------------------------------------------------------------------------
# 5.1 — Create block
# ---------------------------------------------------------------------------

def test_create_block_admin_happy(client, db, seed):
    """SU admin can create a block on any clinic for any patient."""
    pat = seed["patient"]
    clinic = seed["clinic_b"]  # admin doesn't need relationship
    resp = client.post(
        f"/api/v1/patients/{pat.guid}/blocks",
        json={
            "source_scope_type": "clinic",
            "source_scope_id": str(clinic.guid),
            "reason": "patient phoned in request",
        },
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["patient_guid"] == str(pat.guid)
    assert body["source_scope_id"] == str(clinic.guid)
    assert body["source_scope_type"] == "clinic"
    assert body["is_active"] is True
    assert body["lifted_at"] is None
    # An audit row exists.
    rows = db.session.query(AuditLog).filter_by(
        event_type="block.created"
    ).all()
    assert len(rows) == 1
    assert rows[0].patient_guid == pat.guid
    assert rows[0].detail["source_scope_id"] == str(clinic.guid)


def test_create_block_staff_with_relationship_happy(client, db, seed, as_user):
    """Staff at clinic A can create a block for a patient assigned
    there."""
    with as_user(seed["staff_a"]):
        resp = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/blocks",
            json={
                "source_scope_id": str(seed["clinic_b"].guid),
                "reason": "patient requested via phone",
            },
        )
    assert resp.status_code == 201


def test_create_block_staff_unrelated_is_403(client, db, seed, as_user):
    """Staff at clinic B has no relationship to the patient (only at
    clinic A) → 403."""
    # Patient is only at clinic A; staff_b at clinic B has no
    # relationship to the patient.
    with as_user(seed["staff_b"]):
        resp = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/blocks",
            json={"source_scope_id": str(seed["clinic_b"].guid)},
        )
    assert resp.status_code == 403


def test_create_block_duplicate_is_409(client, db, seed):
    pat = seed["patient"]
    scope_id = str(seed["clinic_b"].guid)
    r1 = client.post(
        f"/api/v1/patients/{pat.guid}/blocks",
        json={"source_scope_id": scope_id},
    )
    assert r1.status_code == 201
    r2 = client.post(
        f"/api/v1/patients/{pat.guid}/blocks",
        json={"source_scope_id": scope_id},
    )
    assert r2.status_code == 409
    body = r2.get_json()
    assert "existing_block_guid" in body


def test_create_block_missing_scope_id_is_400(client, db, seed):
    resp = client.post(
        f"/api/v1/patients/{seed['patient'].guid}/blocks",
        json={"source_scope_type": "clinic"},
    )
    assert resp.status_code == 400


def test_create_block_unknown_clinic_is_404(client, db, seed):
    resp = client.post(
        f"/api/v1/patients/{seed['patient'].guid}/blocks",
        json={"source_scope_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


def test_create_block_patient_not_found_is_404(client, db, seed):
    resp = client.post(
        f"/api/v1/patients/{uuid.uuid4()}/blocks",
        json={"source_scope_id": str(seed["clinic_b"].guid)},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5.2 — List
# ---------------------------------------------------------------------------

def test_list_blocks_redacts_for_unrelated_clinic(
    client, db, seed, as_user
):
    """Staff at clinic A lists blocks; one block was made on clinic B's
    data. A clinic-A staff can SEE that 1 block exists but should NOT
    see the source_scope_id (plan §5.2)."""
    pat = seed["patient"]
    # Admin creates a block on clinic B's data.
    client.post(
        f"/api/v1/patients/{pat.guid}/blocks",
        json={"source_scope_id": str(seed["clinic_b"].guid)},
    )
    # Staff at clinic A lists.
    with as_user(seed["staff_a"]):
        resp = client.get(f"/api/v1/patients/{pat.guid}/blocks")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) == 1
    # Redacted: source_scope_id hidden, redacted=True
    assert items[0]["redacted"] is True
    assert items[0]["source_scope_id"] is None


def test_list_blocks_admin_sees_full_details(client, db, seed):
    pat = seed["patient"]
    client.post(
        f"/api/v1/patients/{pat.guid}/blocks",
        json={"source_scope_id": str(seed["clinic_b"].guid)},
    )
    resp = client.get(f"/api/v1/patients/{pat.guid}/blocks")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert items[0]["redacted"] is False
    assert items[0]["source_scope_id"] == str(seed["clinic_b"].guid)
    assert items[0]["source_scope_name"] == seed["clinic_b"].name


# ---------------------------------------------------------------------------
# 5.3 — Lift
# ---------------------------------------------------------------------------

def _create_block(client, patient_guid, scope_id):
    return client.post(
        f"/api/v1/patients/{patient_guid}/blocks",
        json={"source_scope_id": str(scope_id)},
    ).get_json()


def test_lift_consent_happy(client, db, seed):
    pat = seed["patient"]
    block = _create_block(client, pat.guid, seed["clinic_b"].guid)
    resp = client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={"lift_kind": "consent",
              "reason": "patient consented in clinic"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["lift_kind"] == "consent"
    assert body["lifted_at"] is not None
    assert body["lift_expires_at"] is None  # permanent
    assert body["lift_concept_guids"] is None
    assert body["is_active"] is False
    # Audit row
    rows = db.session.query(AuditLog).filter_by(
        event_type="block.lifted"
    ).all()
    assert len(rows) == 1
    assert rows[0].detail["lift_kind"] == "consent"


def test_lift_indispensable_care_requires_mechanical_filter(
    client, db, seed
):
    """Legal 2026-06-04: concept_guids is REQUIRED. Without it → 400."""
    pat = seed["patient"]
    block = _create_block(client, pat.guid, seed["clinic_b"].guid)
    resp = client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={
            "lift_kind": "indispensable_care",
            "reason": "patient unconscious — need allergy data",
        },
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "concept_guids" in body["error"]


def test_lift_indispensable_care_happy(client, db, seed):
    pat = seed["patient"]
    block = _create_block(client, pat.guid, seed["clinic_b"].guid)
    concept_a = str(uuid.uuid4())
    concept_b = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={
            "lift_kind": "indispensable_care",
            "reason": "patient unconscious",
            "concept_guids": [concept_a, concept_b],
            "expires_in": 3600,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["lift_kind"] == "indispensable_care"
    assert set(body["lift_concept_guids"]) == {concept_a, concept_b}
    assert body["lift_expires_at"] is not None
    # Within the lift window it is NOT active (block is lifted).
    assert body["is_active"] is False


def test_lift_unknown_kind_is_400(client, db, seed):
    pat = seed["patient"]
    block = _create_block(client, pat.guid, seed["clinic_b"].guid)
    resp = client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={"lift_kind": "magic", "reason": "x"},
    )
    assert resp.status_code == 400


def test_lift_already_lifted_is_404(client, db, seed):
    pat = seed["patient"]
    block = _create_block(client, pat.guid, seed["clinic_b"].guid)
    client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={"lift_kind": "consent", "reason": "first"},
    )
    resp = client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={"lift_kind": "consent", "reason": "again"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5.4 — Metadata
# ---------------------------------------------------------------------------

def test_metadata_counts_active_only(client, db, seed):
    pat = seed["patient"]
    # Two active blocks (different scopes)
    _create_block(client, pat.guid, seed["clinic_a"].guid)
    block_b = _create_block(client, pat.guid, seed["clinic_b"].guid)
    # Lift one — now only one active.
    client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block_b['guid']}/lift",
        json={"lift_kind": "consent", "reason": "ok"},
    )
    resp = client.get(f"/api/v1/patients/{pat.guid}/blocks/metadata")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["blocked_source_count"] == 1
    assert body["has_active_indispensable_care_lift"] is False


def test_metadata_flags_indispensable_care_lift(client, db, seed):
    pat = seed["patient"]
    block = _create_block(client, pat.guid, seed["clinic_b"].guid)
    client.post(
        f"/api/v1/patients/{pat.guid}/blocks/{block['guid']}/lift",
        json={
            "lift_kind": "indispensable_care",
            "reason": "emergency",
            "concept_guids": [str(uuid.uuid4())],
            "expires_in": 3600,
        },
    )
    resp = client.get(f"/api/v1/patients/{pat.guid}/blocks/metadata")
    body = resp.get_json()
    assert body["has_active_indispensable_care_lift"] is True
    # Block is lifted → not in blocked_source_count.
    assert body["blocked_source_count"] == 0


def test_metadata_patient_not_found_is_404(client, db, seed):
    resp = client.get(f"/api/v1/patients/{uuid.uuid4()}/blocks/metadata")
    assert resp.status_code == 404
