"""IPS Renov 5 (#201) — admin indispensable-care block lift.

Verifies:
- Role gate: SU passes; configured roles ('physician'|'admin') pass;
  other roles 403.
- Required-field validation: reason + concept_guids both mandatory;
  bad concept_guid shapes -> 400; ISO-8601 parse on optional date
  narrowing; expires_in shape.
- State: lifted_at set to now, lift_expires_at = now + 24h (or
  caller-supplied), lift_concept_guids persisted, lift_kind set to
  'indispensable_care'.
- 409 when block already lifted.
- Audit row: event_type='block.lifted', detail.mechanism=
  'indispensable_care', actor_user_guid + reason verbatim.
- The lift integrates with #202: a stale lift_expires_at causes the
  sweep job to flip the row back to active.
- Webhook fires post-commit (block.lifted).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientIndex
from app.models.user import User
from app.services.block_expiry_service import re_impose_indispensable_lifts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def world(client, db):
    """Patient + clinic + an active block."""
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
        family_name="Hagberg",
        given_name="Hilda",
    )
    clinic = Clinic(name="ER", is_active=True)
    db.session.add_all([patient, clinic])
    db.session.flush()
    block = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
    )
    db.session.add(block)
    db.session.commit()
    return {"patient": patient, "clinic": clinic, "block": block}


@pytest.fixture
def silence_webhook(monkeypatch):
    """Don't hit the network during route tests."""
    monkeypatch.setattr(
        "app.api.admin_blocks_routes._emit_block_webhook",
        lambda event, block: None,
    )


@pytest.fixture
def as_user():
    """Re-point the AUTH_DISABLED synthetic user to a specific DB
    User so we can exercise the role gate."""
    @contextmanager
    def _impersonate(user):
        with patch(
            "app.services.auth_service._synthetic_dev_user",
            return_value=user,
        ):
            yield
    return _impersonate


def _make_user(role="operator", is_superuser=False):
    return User(
        username=f"u_{uuid.uuid4().hex[:8]}",
        display_name=f"{role}-user",
        role=role,
        is_active=True,
        is_superuser=is_superuser,
    )


def _payload(*, reason="indispensable care: ER intake", concepts=None,
             expires_in=None, from_date=None, until_date=None):
    body = {
        "reason": reason,
        "concept_guids": concepts or [str(uuid.uuid4())],
    }
    if expires_in is not None:
        body["expires_in"] = expires_in
    if from_date is not None:
        body["from_date"] = from_date
    if until_date is not None:
        body["until_date"] = until_date
    return body


# ---------------------------------------------------------------------------
# Role gate
# ---------------------------------------------------------------------------

class TestRoleGate:
    def test_su_admin_can_lift(
        self, client, db, world, silence_webhook,
    ):
        # Synthetic dev user is is_superuser=True by default.
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(),
        )
        assert r.status_code == 200, r.get_json()

    def test_physician_can_lift(
        self, client, db, world, silence_webhook, as_user,
    ):
        physician = _make_user(role="physician", is_superuser=False)
        db.session.add(physician)
        db.session.commit()
        with as_user(physician):
            r = client.post(
                f"/api/v1/admin/blocks/{world['block'].guid}/lift",
                json=_payload(),
            )
        assert r.status_code == 200

    def test_operator_is_403(
        self, client, db, world, silence_webhook, as_user,
    ):
        op = _make_user(role="operator", is_superuser=False)
        db.session.add(op)
        db.session.commit()
        with as_user(op):
            r = client.post(
                f"/api/v1/admin/blocks/{world['block'].guid}/lift",
                json=_payload(),
            )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Required-field + shape validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_reason_is_400(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json={"concept_guids": [str(uuid.uuid4())]},
        )
        assert r.status_code == 400
        assert "reason" in r.get_json()["error"]

    def test_whitespace_reason_is_400(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json={
                "reason": "   ",
                "concept_guids": [str(uuid.uuid4())],
            },
        )
        assert r.status_code == 400

    def test_missing_concepts_is_400(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json={"reason": "needed"},
        )
        assert r.status_code == 400
        assert "concept_guids" in r.get_json()["error"]

    def test_bad_concept_guid_shape_is_400(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json={
                "reason": "needed",
                "concept_guids": ["not-a-uuid"],
            },
        )
        assert r.status_code == 400

    def test_negative_expires_in_is_400(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(expires_in=-1),
        )
        assert r.status_code == 400

    def test_bad_from_date_is_400(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(from_date="not-a-date"),
        )
        assert r.status_code == 400

    def test_invalid_block_guid_is_404(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            "/api/v1/admin/blocks/not-a-uuid/lift",
            json=_payload(),
        )
        assert r.status_code == 404

    def test_unknown_block_is_404(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{uuid.uuid4()}/lift",
            json=_payload(),
        )
        assert r.status_code == 404

    def test_already_lifted_block_is_409(
        self, client, db, world, silence_webhook,
    ):
        # First lift.
        r1 = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(),
        )
        assert r1.status_code == 200
        # Second lift on the same active row -> 409.
        r2 = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(),
        )
        assert r2.status_code == 409


# ---------------------------------------------------------------------------
# State + audit shape
# ---------------------------------------------------------------------------

class TestStateAndAudit:
    def test_persists_lift_fields_and_default_24h(
        self, client, db, world, silence_webhook,
    ):
        concepts = [str(uuid.uuid4()) for _ in range(2)]
        before = datetime.now(timezone.utc)
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(reason="ER admission", concepts=concepts),
        )
        assert r.status_code == 200
        body = r.get_json()
        # State written back.
        block = db.session.get(PatientBlock, world['block'].guid)
        assert block.lifted_at is not None
        assert block.lift_kind == "indispensable_care"
        assert sorted(block.lift_concept_guids) == sorted(concepts)
        assert block.lifted_reason == "ER admission"
        # 24h default (allow generous slack for test latency).
        delta = block.lift_expires_at - block.lifted_at
        assert timedelta(hours=23, minutes=59) <= delta \
            <= timedelta(hours=24, minutes=1)

    def test_custom_expires_in_honoured(
        self, client, db, world, silence_webhook,
    ):
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(expires_in=3600),
        )
        assert r.status_code == 200
        block = db.session.get(PatientBlock, world['block'].guid)
        delta = block.lift_expires_at - block.lifted_at
        assert timedelta(minutes=59) <= delta <= timedelta(hours=1, minutes=1)

    def test_audit_row_shape(
        self, client, db, world, silence_webhook, as_user,
    ):
        # Use a persisted SU so actor_user_guid is a real UUID string,
        # not the transient (guid=None) dev user.
        su = _make_user(role="admin", is_superuser=True)
        db.session.add(su)
        db.session.commit()
        reason = "Patient unconscious in ER, needs full history"
        concepts = [str(uuid.uuid4())]
        with as_user(su):
            r = client.post(
                f"/api/v1/admin/blocks/{world['block'].guid}/lift",
                json=_payload(reason=reason, concepts=concepts),
            )
        assert r.status_code == 200
        audit = (
            db.session.query(AuditLog)
            .filter_by(
                event_type="block.lifted",
                resource_guid=world['block'].guid,
            )
            .first()
        )
        assert audit is not None
        assert audit.detail["mechanism"] == "indispensable_care"
        assert audit.detail["lift_kind"] == "indispensable_care"
        assert audit.detail["reason"] == reason
        assert audit.detail["lift_concept_guids"] == concepts
        assert audit.detail["admin_route"] is True
        # actor_user_guid carries the persisted SU's guid.
        assert audit.detail["actor_user_guid"] == str(su.guid)


# ---------------------------------------------------------------------------
# Integration with the #202 sweep (auto re-impose)
# ---------------------------------------------------------------------------

class TestAutoReImposeIntegration:
    def test_sweep_re_imposes_after_lift_expires(
        self, client, db, world, silence_webhook, monkeypatch,
    ):
        # Lift via the admin route.
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(expires_in=60),  # 60-second lift
        )
        assert r.status_code == 200
        block = db.session.get(PatientBlock, world['block'].guid)
        assert block.is_active() is False  # currently lifted

        # Silence the sweep's webhook too.
        monkeypatch.setattr(
            "app.services.block_expiry_service.safe_dispatch",
            lambda *a, **k: None,
        )

        # Advance the clock by passing a fake "now" past lift_expires_at.
        future = block.lift_expires_at + timedelta(minutes=5)
        summary = re_impose_indispensable_lifts(at=future)
        assert summary["re_imposed"] == 1
        db.session.refresh(block)
        # Lift record cleared by the sweep -> block back to fresh-active.
        assert block.lifted_at is None
        assert block.lift_kind is None
        assert block.lift_expires_at is None
        assert block.is_active() is True


# ---------------------------------------------------------------------------
# Webhook plumbing
# ---------------------------------------------------------------------------

class TestWebhook:
    def test_lift_fires_block_lifted_webhook(
        self, client, db, world, monkeypatch,
    ):
        fired = []
        monkeypatch.setattr(
            "app.api.admin_blocks_routes._emit_block_webhook",
            lambda event, block: fired.append(
                (event, str(block.guid)),
            ),
        )
        r = client.post(
            f"/api/v1/admin/blocks/{world['block'].guid}/lift",
            json=_payload(),
        )
        assert r.status_code == 200
        assert fired == [("block.lifted", str(world['block'].guid))]
