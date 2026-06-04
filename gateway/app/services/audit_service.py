"""Audit logging service — records security-relevant events."""

import uuid

from flask import request, g

from app.models.base import db
from app.models.audit_log import AuditLog


def current_session_id() -> str | None:
    """Return the SSO session_id ("sid" JWT claim, see ticket #191)
    for the current request, or None if not available.

    Resolution order (ticket #203):
      1. ``X-Operator-Session-Id`` request header — canonical carrier
         for internal API-key callers (sim.pdhc / monitor.pdhc / etc.)
         that don't go through an SSO blob.
      2. ``g.access_blob['session_id']`` — set by ``require_auth`` on
         each fresh /me/service response.
      3. None — legacy caller / AUTH_DISABLED dev blob without the
         claim. Audit row gets NULL; downstream PDL kontroller queries
         must treat NULL as "no session correlation available".
    """
    try:
        header_val = request.headers.get("X-Operator-Session-Id")
    except RuntimeError:
        # No active request context (CLI / background work).
        header_val = None
    if header_val:
        return header_val[:128]
    blob = getattr(g, "access_blob", None)
    if isinstance(blob, dict):
        sid = blob.get("session_id")
        if sid:
            return str(sid)[:128]
    return None


def log_event(
    event_type: str,
    *,
    patient_guid: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_guid: uuid.UUID | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """Create an audit log entry from the current request context."""
    actor = getattr(g, "current_user", None)
    entry = AuditLog(
        actor_guid=actor.guid if actor else None,
        actor_type="user" if actor else "system",
        actor_label=actor.display_name or actor.username if actor else "system",
        patient_guid=patient_guid,
        event_type=event_type,
        resource_type=resource_type,
        resource_guid=resource_guid,
        request_path=request.path if request else None,
        request_method=request.method if request else None,
        ip_address=request.remote_addr if request else None,
        session_id=current_session_id(),
        detail=detail or {},
    )
    db.session.add(entry)
    db.session.flush()
    return entry
