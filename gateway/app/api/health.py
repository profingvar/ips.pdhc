"""Health and metrics endpoints."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify
from sqlalchemy import text

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.audit_log import AuditLog

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@bp.route("/health")
def health():
    """Health check — verifies DB connectivity."""
    try:
        db.session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return jsonify({
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "ips-server",
        "version": "0.1.0",
    })


@bp.route("/metrics")
def metrics():
    """High-level service statistics."""
    try:
        stats = {
            "patients": db.session.query(PatientIndex).count(),
            "fhir_resources": db.session.query(FhirResource).filter_by(status="active").count(),
            "ips_cards": db.session.query(IpsCard).filter_by(status="active").count(),
            "ips_snapshots": db.session.query(IpsSnapshot).count(),
            "audit_events": db.session.query(AuditLog).count(),
        }
    except Exception:
        stats = {}

    return jsonify({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "counts": stats,
    })
