"""Tests for the patient-portal HTML pages — ticket #245.

Pages exercised:
  GET   /patient/blocks                    — list + create form
  POST  /patient/blocks/create             — create
  GET   /patient/blocks/<guid>/lift        — confirm
  POST  /patient/blocks/<guid>/lift        — submit
  GET   /patient/blocks/<guid>/extend      — form
  POST  /patient/blocks/<guid>/extend      — submit
  GET   /patient/consents                  — list + grant form
  POST  /patient/consents/create           — grant
  GET   /patient/consents/<guid>/revoke    — confirm
  POST  /patient/consents/<guid>/revoke    — submit

Auth: TestingConfig sets AUTH_DISABLED=True; require_patient_html
reads ``session['dev_patient_guid']`` which we set via
``client.session_transaction()``.

Cross-patient guards verified — block_guid / consent_guid belonging
to another patient render 404 (same confused-deputy guard as the
JSON API).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.base import db
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed(client, db):
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

    a = PatientIndex(
        fhir_resource_guid=fhir_a.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Andersson",
        given_name="Anna",
    )
    b = PatientIndex(
        fhir_resource_guid=fhir_b.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Bengtsson",
        given_name="Bo",
    )
    db.session.add_all([a, b])
    db.session.flush()

    clinic = Clinic(name="Cardiology A", is_active=True)
    db.session.add(clinic)
    db.session.commit()

    return {"a": a, "b": b, "clinic": clinic}


def _login_as(client, patient_guid):
    with client.session_transaction() as s:
        s["dev_patient_guid"] = str(patient_guid)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_blocks_list_requires_session(client, seed):
    resp = client.get("/patient/blocks")
    assert resp.status_code == 401
    body = resp.get_data(as_text=True)
    assert "patientportal" in body.lower() or "patient" in body.lower()


# ---------------------------------------------------------------------------
# Blocks list
# ---------------------------------------------------------------------------

def test_blocks_list_renders_with_empty_state(client, seed):
    _login_as(client, seed["a"].guid)
    resp = client.get("/patient/blocks")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # The #210 copy's empty_state text appears
    assert "inga aktiva spärrar" in body.lower() or "empty" in body.lower() or "Du har inga" in body
    # Clinic options surfaced for the create form
    assert seed["clinic"].name in body


def test_blocks_list_shows_legal_review_banner_when_draft(client, seed):
    """Bundle ships as draft; banner must appear on every patient
    portal page so production renders are visibly gated."""
    _login_as(client, seed["a"].guid)
    resp = client.get("/patient/blocks")
    body = resp.get_data(as_text=True)
    assert "Förhandsversion" in body
    assert "legal_review_status" in body


def test_blocks_list_shows_indispensable_banner_when_active(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    # Plant a block with an active indispensable-care lift.
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
        lifted_at=datetime.now(timezone.utc) - timedelta(hours=1),
        lifted_by_user_guid=uuid.uuid4(),
        lifted_reason="Trauma — pulling allergies",
        lift_kind="indispensable_care",
        lift_concept_guids=[str(uuid.uuid4())],
        lift_expires_at=datetime.now(timezone.utc) + timedelta(hours=23),
    )
    db.session.add(block)
    db.session.commit()

    _login_as(client, a.guid)
    resp = client.get("/patient/blocks")
    body = resp.get_data(as_text=True)
    # The notification template's subject appears
    assert "oundgänglig vård" in body.lower()
    # The reason verbatim
    assert "Trauma — pulling allergies" in body


# ---------------------------------------------------------------------------
# Create block
# ---------------------------------------------------------------------------

def test_blocks_create_persists_block(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    _login_as(client, a.guid)
    resp = client.post(
        "/patient/blocks/create",
        data={
            "source_scope_id": str(clinic.guid),
            "reason": "privacy",
        },
    )
    assert resp.status_code == 302  # redirect to list
    rows = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=a.guid)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].is_active() is True
    assert rows[0].created_reason == "privacy"
    # Audit row with ui marker
    audit = (
        db.session.query(AuditLog)
        .filter(AuditLog.event_type == "block.created",
                AuditLog.patient_guid == a.guid)
        .one()
    )
    assert audit.detail["ui"] == "patient_portal_html"


def test_blocks_create_rejects_invalid_scope(client, seed):
    a = seed["a"]
    _login_as(client, a.guid)
    resp = client.post(
        "/patient/blocks/create",
        data={
            "source_scope_id": "not-a-uuid",
        },
    )
    assert resp.status_code == 302
    assert (
        db.session.query(PatientBlock).filter_by(patient_guid=a.guid).count()
        == 0
    )


def test_blocks_create_duplicate_active_blocked(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    db.session.add(PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
    ))
    db.session.commit()
    _login_as(client, a.guid)
    resp = client.post(
        "/patient/blocks/create",
        data={"source_scope_id": str(clinic.guid)},
    )
    assert resp.status_code == 302
    # Still only one row
    assert (
        db.session.query(PatientBlock).filter_by(patient_guid=a.guid).count()
        == 1
    )


# ---------------------------------------------------------------------------
# Lift
# ---------------------------------------------------------------------------

def test_lift_form_renders(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    b = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(b)
    db.session.commit()

    _login_as(client, a.guid)
    resp = client.get(f"/patient/blocks/{b.guid}/lift")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert clinic.name in body
    assert "Häv spärren" in body


def test_lift_submit_marks_consent_lift(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    b = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(b)
    db.session.commit()
    bg = b.guid

    _login_as(client, a.guid)
    resp = client.post(
        f"/patient/blocks/{bg}/lift",
        data={"reason": "ny bedömning"},
    )
    assert resp.status_code == 302

    row = db.session.get(PatientBlock, bg)
    assert row.lift_kind == "consent"
    assert row.lifted_reason == "ny bedömning"
    assert row.is_active() is False


def test_cross_patient_lift_404(client, seed):
    """B cannot lift A's block — should look the same as 'no such block'."""
    a = seed["a"]
    b = seed["b"]
    clinic = seed["clinic"]
    block = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(block)
    db.session.commit()
    bg = block.guid

    _login_as(client, b.guid)
    resp = client.get(f"/patient/blocks/{bg}/lift")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Extend
# ---------------------------------------------------------------------------

def test_extend_form_renders(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    b = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(b)
    db.session.commit()

    _login_as(client, a.guid)
    resp = client.get(f"/patient/blocks/{b.guid}/extend")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Quick-pick buttons present
    assert "+7 dagar" in body
    assert "+30 dagar" in body


def test_extend_quick_days_pushes_forward(client, seed):
    a = seed["a"]
    clinic = seed["clinic"]
    b = PatientBlock(
        patient_guid=a.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=a.guid,
    )
    db.session.add(b)
    db.session.commit()
    bg = b.guid

    _login_as(client, a.guid)
    resp = client.post(
        f"/patient/blocks/{bg}/extend",
        data={"quick_days": "30"},
    )
    assert resp.status_code == 302
    row = db.session.get(PatientBlock, bg)
    assert row.expires_at is not None
    expires_aware = row.expires_at
    if expires_aware.tzinfo is None:
        expires_aware = expires_aware.replace(tzinfo=timezone.utc)
    assert expires_aware > datetime.now(timezone.utc) + timedelta(days=25)


# ---------------------------------------------------------------------------
# Consents — list, grant, revoke
# ---------------------------------------------------------------------------

def test_consents_list_renders(client, seed):
    a = seed["a"]
    _login_as(client, a.guid)
    resp = client.get("/patient/consents")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Mina samtycken" in body
    assert "Ge nytt samtycke" in body


def test_consents_grant_persists(client, seed):
    a = seed["a"]
    grantee = uuid.uuid4()
    _login_as(client, a.guid)
    resp = client.post(
        "/patient/consents/create",
        data={"grantee_caregiver_guid": str(grantee)},
    )
    assert resp.status_code == 302
    row = (
        db.session.query(PatientConsent)
        .filter_by(patient_guid=a.guid)
        .one()
    )
    assert row.grantee_caregiver_guid == grantee
    assert row.granted_via == "portal"


def test_consents_grant_invalid_guid(client, seed):
    a = seed["a"]
    _login_as(client, a.guid)
    resp = client.post(
        "/patient/consents/create",
        data={"grantee_caregiver_guid": "not-a-uuid"},
    )
    assert resp.status_code == 302
    assert (
        db.session.query(PatientConsent).filter_by(patient_guid=a.guid).count()
        == 0
    )


def test_consents_revoke_form_renders(client, seed):
    a = seed["a"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    _login_as(client, a.guid)
    resp = client.get(f"/patient/consents/{consent.guid}/revoke")
    assert resp.status_code == 200
    assert "Återkalla" in resp.get_data(as_text=True)


def test_consents_revoke_submit(client, seed):
    a = seed["a"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    cg = consent.guid
    _login_as(client, a.guid)
    resp = client.post(
        f"/patient/consents/{cg}/revoke",
        data={"reason": "ändrat mig"},
    )
    assert resp.status_code == 302
    row = db.session.get(PatientConsent, cg)
    assert row.revoked_at is not None
    assert row.revoked_reason == "ändrat mig"


def test_cross_patient_consent_revoke_404(client, seed):
    a, b = seed["a"], seed["b"]
    consent = PatientConsent(
        patient_guid=a.guid,
        grantee_caregiver_guid=uuid.uuid4(),
        granted_via="portal",
        granted_by_user_guid=a.guid,
    )
    db.session.add(consent)
    db.session.commit()
    cg = consent.guid
    _login_as(client, b.guid)
    resp = client.get(f"/patient/consents/{cg}/revoke")
    assert resp.status_code == 404
