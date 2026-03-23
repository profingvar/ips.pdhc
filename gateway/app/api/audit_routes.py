"""Audit log query endpoint."""

from datetime import datetime

from flask import Blueprint, jsonify, request

from app.models.base import db
from app.models.audit_log import AuditLog
from app.services.auth_service import require_auth

bp = Blueprint("audit_api", __name__, url_prefix="/api/v1/audit")


@bp.route("", methods=["GET"])
@require_auth
def query_audit():
    """Query audit events with filters."""
    query = db.session.query(AuditLog)

    actor_guid = request.args.get("actor_guid")
    patient_guid = request.args.get("patient_guid")
    event_type = request.args.get("event_type")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    limit = min(int(request.args.get("limit", 100)), 1000)

    if actor_guid:
        query = query.filter_by(actor_guid=actor_guid)
    if patient_guid:
        query = query.filter_by(patient_guid=patient_guid)
    if event_type:
        query = query.filter_by(event_type=event_type)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            query = query.filter(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            query = query.filter(AuditLog.created_at <= dt)
        except ValueError:
            pass

    events = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in events])
