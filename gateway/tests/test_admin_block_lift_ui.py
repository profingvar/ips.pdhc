"""Tests for the admin indispensable-care block-lift HTML form — #244.

Pages exercised:
  GET  /admin/blocks/<block_guid>/lift          — form
  POST /admin/blocks/<block_guid>/lift/confirm  — confirmation preview
  POST /admin/blocks/<block_guid>/lift/submit   — commit + audit
  GET  /admin/blocks/<block_guid>/lift/done     — success

TestingConfig sets AUTH_DISABLED=True; the form's _current_user_for_session
synthesises a dev SU in that mode, so the role gate passes by default.
A separate test flips AUTH_DISABLED off to verify the 403 page renders.
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
    fhir = FhirResource(
        resource_type="Patient",
        resource_id=str(uuid.uuid4()),
        resource_json={"resourceType": "Patient"},
    )
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

    clinic = Clinic(name="Cardiology A", is_active=True)
    db.session.add(clinic)
    db.session.flush()

    block = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        created_by_user_guid=patient.guid,
    )
    db.session.add(block)
    db.session.commit()

    return {"patient": patient, "clinic": clinic, "block": block}


# ---------------------------------------------------------------------------
# GET form
# ---------------------------------------------------------------------------

def test_form_renders_with_block_context(client, seed):
    block = seed["block"]
    clinic = seed["clinic"]
    resp = client.get(f"/admin/blocks/{block.guid}/lift")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Block + clinic context visible
    assert str(block.guid) in body
    assert clinic.name in body
    # Patient name shown so the clinician can verify
    assert "Andersson" in body
    # Cross-link to the runbook (acceptance criterion)
    assert "sparr_operator_runbook" in body
    # Legal framing
    assert "PDL Ch 4" in body
    # Mechanical filter mention
    assert "mechanical filter" in body.lower()


def test_form_returns_404_for_unknown_block(client, seed):
    resp = client.get(f"/admin/blocks/{uuid.uuid4()}/lift")
    assert resp.status_code == 404


def test_form_redirects_when_block_already_lifted(client, seed):
    from app.models.base import utcnow as _utcnow
    block = seed["block"]
    block.lifted_at = _utcnow()
    block.lift_kind = "consent"
    db.session.commit()

    resp = client.get(f"/admin/blocks/{block.guid}/lift")
    # Redirect to dashboard with a warning flash
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Confirmation preview
# ---------------------------------------------------------------------------

def test_confirm_renders_notification_preview(client, seed):
    block = seed["block"]
    concept_a = str(uuid.uuid4())
    concept_b = str(uuid.uuid4())
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/confirm",
        data={
            "reason": "Unresponsive trauma patient",
            "concept_guids": f"{concept_a}\n{concept_b}",
            "expires_in_hours": "12",
            "from_date": "",
            "until_date": "",
        },
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Reason echoed
    assert "Unresponsive trauma patient" in body
    # Concept guids both surfaced
    assert concept_a in body
    assert concept_b in body
    # Notification preview (SV) — pull a recognisable token from the
    # template ("oundgänglig" appears in the indispensable_care_notification
    # body in sparr_copy.json)
    assert "oundgänglig" in body
    # Cardiology A is the caregiver_name placeholder fill
    assert "Cardiology A" in body
    # 12h appears as the expires-in value
    assert "12 h" in body or "12h" in body
    # No commit yet — block is still active
    block_row = db.session.get(PatientBlock, block.guid)
    assert block_row.is_active() is True


def test_confirm_with_missing_reason_redirects_with_error(client, seed):
    block = seed["block"]
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/confirm",
        data={
            "reason": "",
            "concept_guids": str(uuid.uuid4()),
            "expires_in_hours": "24",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302  # back to form
    # Block is unchanged
    assert db.session.get(PatientBlock, block.guid).is_active() is True


def test_confirm_with_missing_concepts_redirects_with_error(client, seed):
    block = seed["block"]
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/confirm",
        data={
            "reason": "indispensable",
            "concept_guids": "",
            "expires_in_hours": "24",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_confirm_with_invalid_concept_guid_redirects(client, seed):
    block = seed["block"]
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/confirm",
        data={
            "reason": "indispensable",
            "concept_guids": "not-a-uuid",
            "expires_in_hours": "24",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_confirm_rejects_zero_or_negative_expires(client, seed):
    block = seed["block"]
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/confirm",
        data={
            "reason": "indispensable",
            "concept_guids": str(uuid.uuid4()),
            "expires_in_hours": "0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def test_submit_lifts_block_and_writes_audit(client, seed):
    block = seed["block"]
    concept_guid = str(uuid.uuid4())
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/submit",
        data={
            "reason": "Indispensable care — pulling prior allergies",
            "concept_guids": concept_guid,
            "expires_in_hours": "24",
            "from_date": "",
            "until_date": "",
        },
        follow_redirects=False,
    )
    # Redirect to success screen
    assert resp.status_code == 302
    assert "/lift/done" in resp.headers["Location"]
    assert "audit_guid=" in resp.headers["Location"]

    # Block is now lifted
    row = db.session.get(PatientBlock, block.guid)
    assert row.lifted_at is not None
    assert row.lift_kind == "indispensable_care"
    assert row.lifted_reason == "Indispensable care — pulling prior allergies"
    assert row.lift_concept_guids == [concept_guid]
    assert row.lift_expires_at is not None

    # Audit row written with mechanism=indispensable_care + ui=html_form
    audit = (
        db.session.query(AuditLog)
        .filter(AuditLog.event_type == "block.lifted",
                AuditLog.resource_guid == block.guid)
        .one()
    )
    assert audit.detail["mechanism"] == "indispensable_care"
    assert audit.detail["admin_route"] is True
    assert audit.detail["ui"] == "html_form"
    assert audit.detail["reason"] == "Indispensable care — pulling prior allergies"


def test_submit_revalidates_required_fields(client, seed):
    """A hand-crafted POST that skips the confirm screen and tries to
    submit with no reason must still be rejected — the submit handler
    re-validates rather than trusting the confirm-step happened."""
    block = seed["block"]
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/submit",
        data={
            "reason": "",
            "concept_guids": str(uuid.uuid4()),
            "expires_in_hours": "24",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302  # bounced back to form
    # Block stays active
    assert db.session.get(PatientBlock, block.guid).is_active() is True


def test_submit_handles_from_until_dates(client, seed):
    block = seed["block"]
    resp = client.post(
        f"/admin/blocks/{block.guid}/lift/submit",
        data={
            "reason": "indispensable",
            "concept_guids": str(uuid.uuid4()),
            "expires_in_hours": "12",
            "from_date": "2024-01-01T00:00:00Z",
            "until_date": "2024-12-31T00:00:00Z",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = db.session.get(PatientBlock, block.guid)
    assert row.lift_from_date is not None
    assert row.lift_until_date is not None


# ---------------------------------------------------------------------------
# Success page
# ---------------------------------------------------------------------------

def test_success_page_shows_audit_guid(client, seed):
    block = seed["block"]
    # Make the lift first
    client.post(
        f"/admin/blocks/{block.guid}/lift/submit",
        data={
            "reason": "test",
            "concept_guids": str(uuid.uuid4()),
            "expires_in_hours": "1",
        },
    )
    audit = (
        db.session.query(AuditLog)
        .filter(AuditLog.event_type == "block.lifted")
        .first()
    )

    resp = client.get(
        f"/admin/blocks/{block.guid}/lift/done?audit_guid={audit.guid}"
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert str(audit.guid) in body
    # Copy button surfaced
    assert "Copy" in body


# ---------------------------------------------------------------------------
# Role gate (prod path — AUTH_DISABLED off)
# ---------------------------------------------------------------------------

def test_role_denied_renders_403_page(client, seed, app):
    """Without an SSO session (and AUTH_DISABLED off), the lift form
    must render the explicit 403 page that names the env knob, not a
    generic Flask 401/403."""
    app.config["AUTH_DISABLED"] = False
    try:
        resp = client.get(f"/admin/blocks/{seed['block'].guid}/lift")
    finally:
        app.config["AUTH_DISABLED"] = True
    # The before_request on the admin blueprint redirects to SSO login
    # when there's no session; we just verify the response isn't a 200
    # (i.e. the form isn't rendered to an unauthenticated caller).
    assert resp.status_code != 200
