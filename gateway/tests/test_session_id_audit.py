"""Tests for ips.pdhc AuditLog.session_id (ticket #203) — propagates
the SSO session_id (sid JWT claim, ticket #191) into ips's existing
audit_log so multi-request reads chain back to one operator session
(Lag (2022:913) chain-of-custody).

Sources of session_id, in priority order (see
audit_service.current_session_id):
  1. X-Operator-Session-Id request header
  2. g.access_blob['session_id']
  3. None (legacy callers / no request context)
"""
from __future__ import annotations

from flask import g

from app.models.audit_log import AuditLog
from app.services import audit_service


# ---------------------------------------------------------------------------
# current_session_id() resolution
# ---------------------------------------------------------------------------

def test_current_session_id_prefers_header_over_blob(app):
    with app.test_request_context(
        "/some/path",
        headers={"X-Operator-Session-Id": "sid-from-header"},
    ):
        g.access_blob = {"session_id": "sid-from-blob"}
        assert audit_service.current_session_id() == "sid-from-header"


def test_current_session_id_falls_back_to_blob(app):
    with app.test_request_context("/some/path"):
        g.access_blob = {"session_id": "sid-from-blob"}
        assert audit_service.current_session_id() == "sid-from-blob"


def test_current_session_id_none_when_no_blob_no_header(app):
    with app.test_request_context("/some/path"):
        assert audit_service.current_session_id() is None


def test_current_session_id_truncates_oversized_header(app):
    """The column is String(128); the resolver caps to avoid silent
    truncation surprises later in the request."""
    with app.test_request_context(
        "/some/path",
        headers={"X-Operator-Session-Id": "x" * 200},
    ):
        sid = audit_service.current_session_id()
        assert sid is not None
        assert len(sid) == 128


def test_current_session_id_no_request_context_returns_none(app):
    """CLI / scripts / background work — no Flask request, no error."""
    with app.app_context():  # app context only, no request
        assert audit_service.current_session_id() is None


# ---------------------------------------------------------------------------
# log_event populates session_id
# ---------------------------------------------------------------------------

def test_log_event_picks_up_header_sid(client, db):
    """log_event called in a request that has X-Operator-Session-Id
    writes that value into the audit row."""
    from app import create_app  # noqa
    # client uses the session-scoped app; just need a request context here.
    with client.application.test_request_context(
        "/api/v1/health",
        headers={"X-Operator-Session-Id": "sid-end-to-end"},
    ):
        entry = audit_service.log_event(
            event_type="patient.read",
            detail={"reason": "test"},
        )
        db.session.commit()
        assert entry.session_id == "sid-end-to-end"

        fetched = AuditLog.query.filter_by(event_type="patient.read").first()
        assert fetched is not None
        assert fetched.session_id == "sid-end-to-end"


def test_log_event_picks_up_blob_sid(client, db):
    """When no header is present, the blob carries the sid."""
    with client.application.test_request_context("/api/v1/health"):
        g.access_blob = {"session_id": "sid-from-validated-blob"}
        entry = audit_service.log_event(event_type="patient.list")
        db.session.commit()
        assert entry.session_id == "sid-from-validated-blob"


def test_log_event_null_session_id_for_legacy_caller(client, db):
    """No header AND no blob → row gets NULL session_id, write still
    succeeds (the column is nullable). Mirrors API-key callers that
    don't yet forward X-Operator-Session-Id."""
    with client.application.test_request_context("/api/v1/health"):
        entry = audit_service.log_event(event_type="apikey.action")
        db.session.commit()
        assert entry.session_id is None

        fetched = AuditLog.query.filter_by(event_type="apikey.action").first()
        assert fetched.session_id is None


def test_to_dict_exposes_session_id(client, db):
    with client.application.test_request_context(
        "/api/v1/health",
        headers={"X-Operator-Session-Id": "sid-dict"},
    ):
        entry = audit_service.log_event(event_type="evt")
        db.session.commit()
        d = entry.to_dict()
        assert "session_id" in d
        assert d["session_id"] == "sid-dict"
