"""IPS Renov 6 (#202) — background block expiry sweep + outbound webhook.

Three layers:

1. ``services/block_webhook`` — signature helper + dispatcher.
   Verifies the HMAC-SHA256 contract and the payload shape so
   subscribers can implement against a stable spec.
2. ``services/block_expiry_service`` — sweep correctness.
   ``expire_blocks`` flips ``expires_at``-past rows; the model's
   ``is_active`` reflects it; AuditLog rows record ``block.expired``.
   ``re_impose_indispensable_lifts`` flips lifts past
   ``lift_expires_at`` back to active; AuditLog records
   ``block.re_imposed``.
3. End-to-end via the REST surface: create_block / lift_block fire
   the webhook (smoke-tested with the same dispatcher hook the sweep
   uses).
"""
from __future__ import annotations

import hmac
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientIndex
from app.services import block_webhook as bw
from app.services.block_expiry_service import (
    expire_blocks,
    re_impose_indispensable_lifts,
    sweep,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def patient(client, db):
    fhir = FhirResource(
        resource_type="Patient",
        resource_id=str(uuid.uuid4()),
        resource_json={"resourceType": "Patient"},
    )
    db.session.add(fhir)
    db.session.flush()
    p = PatientIndex(
        fhir_resource_guid=fhir.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Eklund",
        given_name="Erik",
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def clinic(client, db):
    c = Clinic(name="ExpiryClinic", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _new_block(
    db, patient, clinic, *,
    expires_at=None,
    lifted_at=None,
    lift_kind=None,
    lift_expires_at=None,
):
    b = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type="clinic",
        source_scope_id=clinic.guid,
        expires_at=expires_at,
        lifted_at=lifted_at,
        lift_kind=lift_kind,
        lift_expires_at=lift_expires_at,
    )
    db.session.add(b)
    db.session.commit()
    return b


# ---------------------------------------------------------------------------
# Layer 1: webhook signing + dispatch
# ---------------------------------------------------------------------------

class TestSignature:
    def test_signature_format_and_value(self):
        sig = bw.compute_signature("the-secret", b"hello world")
        # Stable expected digest.
        expected = (
            "sha256="
            + hmac.new(
                b"the-secret", b"hello world", hashlib.sha256,
            ).hexdigest()
        )
        assert sig == expected
        assert sig.startswith("sha256=")
        assert len(sig) == len("sha256=") + 64  # hex SHA-256

    def test_body_shape_is_canonical(self, client, db, patient, clinic):
        block = _new_block(db, patient, clinic)
        body_bytes = bw._build_body("block.created", block)
        payload = json.loads(body_bytes)
        assert payload["event_type"] == "block.created"
        assert payload["block_guid"] == str(block.guid)
        assert payload["patient_guid"] == str(patient.guid)
        assert payload["source_scope_type"] == "clinic"
        assert payload["source_scope_id"] == str(clinic.guid)
        assert payload["is_active"] is True
        # Canonical: keys sorted, no whitespace.
        assert body_bytes.decode().startswith('{"block_guid":')
        assert b" " not in body_bytes


class TestDispatch:
    def _setup(self, app, monkeypatch, *, targets=None, secret="s3cr3t"):
        app.config["IPS_WEBHOOK_SECRET"] = secret
        if targets is None:
            targets = ["http://sub-a/cb", "http://sub-b/cb"]
        app.config["IPS_WEBHOOK_TARGETS"] = list(targets)
        captured = []

        def fake_post(url, content=None, headers=None, timeout=None):
            captured.append({
                "url": url, "data": content,
                "headers": headers, "timeout": timeout,
            })
            r = MagicMock()
            r.status_code = 200
            return r

        monkeypatch.setattr(bw.httpx, "post", fake_post)
        return captured

    def test_dispatch_signs_and_posts_each_target(
        self, app, monkeypatch, client, db, patient, clinic,
    ):
        captured = self._setup(app, monkeypatch)
        block = _new_block(db, patient, clinic)
        with app.app_context():
            summary = bw.dispatch_block_event("block.created", block)
        assert summary["delivered"] == 2
        assert summary["failed"] == 0
        # All posts share the same body + signature.
        bodies = {c["data"] for c in captured}
        sigs = {c["headers"]["X-PDHC-Signature"] for c in captured}
        assert len(bodies) == 1
        assert len(sigs) == 1
        sig = sigs.pop()
        # Subscriber-side verifier: re-sign with the secret and compare.
        body = bodies.pop()
        expected = bw.compute_signature("s3cr3t", body)
        assert sig == expected
        # X-PDHC-Event carries the event type for cheap routing.
        events = {c["headers"]["X-PDHC-Event"] for c in captured}
        assert events == {"block.created"}

    def test_dispatch_skips_when_secret_missing(
        self, app, monkeypatch, client, db, patient, clinic,
    ):
        self._setup(app, monkeypatch, secret="")
        block = _new_block(db, patient, clinic)
        with app.app_context():
            summary = bw.dispatch_block_event("block.created", block)
        assert summary["skipped"] == "no_secret"
        assert summary["delivered"] == 0

    def test_dispatch_skips_when_no_targets(
        self, app, monkeypatch, client, db, patient, clinic,
    ):
        self._setup(app, monkeypatch, targets=[])
        block = _new_block(db, patient, clinic)
        with app.app_context():
            summary = bw.dispatch_block_event("block.created", block)
        assert summary["skipped"] == "no_targets"

    def test_dispatch_counts_http_failures(
        self, app, monkeypatch, client, db, patient, clinic,
    ):
        app.config["IPS_WEBHOOK_SECRET"] = "k"
        app.config["IPS_WEBHOOK_TARGETS"] = [
            "http://ok/cb", "http://bad/cb",
        ]

        def fake_post(url, content=None, headers=None, timeout=None):
            r = MagicMock()
            r.status_code = 200 if "ok" in url else 500
            return r

        monkeypatch.setattr(bw.httpx, "post", fake_post)
        block = _new_block(db, patient, clinic)
        with app.app_context():
            summary = bw.dispatch_block_event("block.created", block)
        assert summary["delivered"] == 1
        assert summary["failed"] == 1

    def test_dispatch_rejects_unknown_event(
        self, app, client, db, patient, clinic,
    ):
        block = _new_block(db, patient, clinic)
        with app.app_context():
            with pytest.raises(ValueError):
                bw.dispatch_block_event("not.a.real.event", block)

    def test_safe_dispatch_swallows_exceptions(
        self, app, monkeypatch, client, db, patient, clinic, caplog,
    ):
        # Force the dispatcher to raise — safe_dispatch must not.
        def boom(*a, **k):  # noqa: ANN002
            raise RuntimeError("dispatcher broke")

        monkeypatch.setattr(
            bw, "dispatch_block_event", boom,
        )
        block = _new_block(db, patient, clinic)
        with app.app_context():
            bw.safe_dispatch("block.created", block)  # does not raise


# ---------------------------------------------------------------------------
# Layer 2: sweep correctness
# ---------------------------------------------------------------------------

@pytest.fixture
def silence_webhook(monkeypatch):
    """Replace safe_dispatch in the sweep service so tests focus on DB
    transitions; signed-webhook coverage lives in TestDispatch."""
    monkeypatch.setattr(
        "app.services.block_expiry_service.safe_dispatch",
        lambda *a, **k: None,
    )


class TestExpireBlocks:
    def test_expires_past_deadline(
        self, client, db, patient, clinic, silence_webhook,
    ):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        block = _new_block(db, patient, clinic, expires_at=past)
        # Before sweep: is_active reflects the time-bound expiry too.
        assert block.is_active() is False
        summary = expire_blocks()
        assert summary["expired"] == 1
        assert summary["block_guids"] == [str(block.guid)]

        db.session.refresh(block)
        assert block.lifted_at is not None
        assert block.lifted_reason == "expired"
        # Audit row written.
        events = (
            db.session.query(AuditLog)
            .filter_by(event_type="block.expired",
                       resource_guid=block.guid)
            .count()
        )
        assert events == 1

    def test_does_not_expire_future_deadline(
        self, client, db, patient, clinic, silence_webhook,
    ):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        block = _new_block(db, patient, clinic, expires_at=future)
        summary = expire_blocks()
        assert summary["expired"] == 0
        db.session.refresh(block)
        assert block.lifted_at is None
        assert block.is_active() is True

    def test_does_not_re_expire_already_lifted(
        self, client, db, patient, clinic, silence_webhook,
    ):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        # Already lifted by a consent flow — sweep must not touch it.
        block = _new_block(
            db, patient, clinic,
            expires_at=past,
            lifted_at=datetime.now(timezone.utc) - timedelta(hours=1),
            lift_kind="consent",
        )
        summary = expire_blocks()
        assert summary["expired"] == 0
        db.session.refresh(block)
        # Lifted-by-consent stays as-is.
        assert block.lift_kind == "consent"

    def test_skips_blocks_without_expires_at(
        self, client, db, patient, clinic, silence_webhook,
    ):
        block = _new_block(db, patient, clinic)  # expires_at=None
        summary = expire_blocks()
        assert summary["expired"] == 0
        db.session.refresh(block)
        assert block.lifted_at is None


class TestReImposeIndispensableLifts:
    def test_re_imposes_after_lift_expires(
        self, client, db, patient, clinic, silence_webhook,
    ):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        lifted_at = past - timedelta(hours=24)
        block = _new_block(
            db, patient, clinic,
            lifted_at=lifted_at,
            lift_kind="indispensable_care",
            lift_expires_at=past,
        )
        block.lifted_reason = "patient in emergency room"
        block.lift_concept_guids = ["a-concept"]
        db.session.commit()

        summary = re_impose_indispensable_lifts()
        assert summary["re_imposed"] == 1
        db.session.refresh(block)
        # The lift record is fully cleared — block back to fresh active.
        assert block.lifted_at is None
        assert block.lift_kind is None
        assert block.lift_expires_at is None
        assert block.lifted_reason is None
        assert block.lift_concept_guids is None
        assert block.is_active() is True
        events = (
            db.session.query(AuditLog)
            .filter_by(event_type="block.re_imposed",
                       resource_guid=block.guid)
            .count()
        )
        assert events == 1

    def test_skips_lifts_still_in_window(
        self, client, db, patient, clinic, silence_webhook,
    ):
        future = datetime.now(timezone.utc) + timedelta(hours=12)
        block = _new_block(
            db, patient, clinic,
            lifted_at=datetime.now(timezone.utc) - timedelta(hours=4),
            lift_kind="indispensable_care",
            lift_expires_at=future,
        )
        summary = re_impose_indispensable_lifts()
        assert summary["re_imposed"] == 0
        db.session.refresh(block)
        assert block.lifted_at is not None

    def test_does_not_touch_consent_lifts(
        self, client, db, patient, clinic, silence_webhook,
    ):
        # consent lifts are permanent — sweep must never re-impose.
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        block = _new_block(
            db, patient, clinic,
            lifted_at=past,
            lift_kind="consent",
            lift_expires_at=None,
        )
        summary = re_impose_indispensable_lifts()
        assert summary["re_imposed"] == 0
        db.session.refresh(block)
        assert block.lift_kind == "consent"


class TestSweepOneShot:
    def test_sweep_runs_both_passes(
        self, client, db, patient, clinic, silence_webhook,
    ):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        expired_block = _new_block(db, patient, clinic, expires_at=past)
        re_impose_block = _new_block(
            db, patient, clinic,
            lifted_at=past - timedelta(hours=24),
            lift_kind="indispensable_care",
            lift_expires_at=past,
        )
        out = sweep()
        assert out["expired"]["expired"] == 1
        assert out["re_imposed"]["re_imposed"] == 1
        db.session.refresh(expired_block)
        db.session.refresh(re_impose_block)
        assert expired_block.lifted_reason == "expired"
        assert re_impose_block.lifted_at is None


# ---------------------------------------------------------------------------
# Layer 3: route -> webhook end-to-end
# ---------------------------------------------------------------------------

class TestRouteFiresWebhook:
    def test_create_block_fires_block_created(
        self, client, db, patient, clinic, monkeypatch,
    ):
        fired = []
        monkeypatch.setattr(
            "app.api.blocks_routes._emit_block_webhook",
            lambda event, block: fired.append(
                (event, str(block.guid)),
            ),
        )
        r = client.post(
            f"/api/v1/patients/{patient.guid}/blocks",
            json={
                "source_scope_type": "clinic",
                "source_scope_id": str(clinic.guid),
                "reason": "test",
            },
        )
        assert r.status_code == 201
        assert len(fired) == 1
        assert fired[0][0] == "block.created"

    def test_lift_block_fires_block_lifted(
        self, client, db, patient, clinic, monkeypatch,
    ):
        # First create a block.
        r = client.post(
            f"/api/v1/patients/{patient.guid}/blocks",
            json={
                "source_scope_type": "clinic",
                "source_scope_id": str(clinic.guid),
            },
        )
        assert r.status_code == 201
        block_guid = r.get_json()["guid"]
        fired = []
        monkeypatch.setattr(
            "app.api.blocks_routes._emit_block_webhook",
            lambda event, block: fired.append(
                (event, str(block.guid)),
            ),
        )
        r = client.post(
            f"/api/v1/patients/{patient.guid}/blocks/{block_guid}/lift",
            json={"lift_kind": "consent", "reason": "patient ok"},
        )
        assert r.status_code == 200
        assert any(e == "block.lifted" for e, _ in fired)
