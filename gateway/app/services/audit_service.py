"""Audit logging service — records security-relevant events."""

import uuid

from flask import request, g

from app.models.base import db
from app.models.audit_log import AuditLog


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
        detail=detail or {},
    )
    db.session.add(entry)
    db.session.flush()
    return entry
