"""Admin UI blueprint — lightweight operator dashboard."""

import json
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, abort, make_response
from sqlalchemy import text, func, or_

from app.models.base import db
from app.models.patient_index import PatientIndex
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.audit_log import AuditLog

bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
)


@bp.route("/")
def dashboard():
    """Admin dashboard — service status and resource counts."""
    try:
        db.session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    counts = {}
    try:
        counts = {
            "patients": db.session.query(PatientIndex).count(),
            "resources": db.session.query(FhirResource).filter_by(status="active").count(),
            "cards": db.session.query(IpsCard).filter_by(status="active").count(),
            "snapshots": db.session.query(IpsSnapshot).count(),
            "push_jobs": db.session.query(PushJob).count(),
            "audit_events": db.session.query(AuditLog).count(),
        }
    except Exception:
        pass

    recent_audit = []
    try:
        recent_audit = db.session.query(AuditLog).order_by(
            AuditLog.created_at.desc()
        ).limit(20).all()
    except Exception:
        pass

    return render_template(
        "dashboard.html",
        db_status=db_status,
        counts=counts,
        recent_audit=recent_audit,
    )


@bp.route("/patients")
def patients():
    """Patient browser — search and list patients."""
    q = request.args.get("q", "").strip()

    query = db.session.query(PatientIndex).order_by(PatientIndex.family_name)

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                PatientIndex.family_name.ilike(like_q),
                PatientIndex.given_name.ilike(like_q),
                PatientIndex.identifier_value.ilike(like_q),
            )
        )

    patients_list = query.limit(100).all()

    # Attach counts for display
    for p in patients_list:
        p.card_count = db.session.query(IpsCard).filter_by(patient_guid=p.guid).count()
        p.resource_count = db.session.query(FhirResource).filter_by(
            patient_guid=p.guid, status="active"
        ).count()

    return render_template("patients.html", patients=patients_list, q=q)


@bp.route("/patients/<uuid:guid>")
def patient_detail(guid):
    """Patient detail — resources, cards, and snapshots."""
    patient = db.session.get(PatientIndex, guid)
    if not patient:
        abort(404)

    resources = db.session.query(FhirResource).filter_by(
        patient_guid=guid, status="active"
    ).order_by(FhirResource.resource_type, FhirResource.last_updated.desc()).all()

    cards = db.session.query(IpsCard).filter_by(
        patient_guid=guid
    ).order_by(IpsCard.created_at.desc()).all()

    snapshots = db.session.query(IpsSnapshot).join(IpsCard).filter(
        IpsCard.patient_guid == guid
    ).order_by(IpsSnapshot.created_at.desc()).all()

    return render_template(
        "patient_detail.html",
        patient=patient,
        resources=resources,
        cards=cards,
        snapshots=snapshots,
        snapshot_count=len(snapshots),
    )


@bp.route("/push")
def push_monitor():
    """Push monitor — destinations, jobs, statuses."""
    status_filter = request.args.get("status", "").strip()

    # Destinations with job counts
    destinations = db.session.query(PushDestination).order_by(
        PushDestination.name
    ).all()
    for d in destinations:
        d.job_count = db.session.query(PushJob).filter_by(
            destination_guid=d.guid
        ).count()

    # Jobs
    job_query = db.session.query(PushJob).order_by(PushJob.created_at.desc())
    if status_filter:
        job_query = job_query.filter_by(status=status_filter)
    jobs = job_query.limit(100).all()

    # Stats
    stats = {
        "queued": db.session.query(PushJob).filter_by(status="queued").count(),
        "in_progress": db.session.query(PushJob).filter_by(status="in_progress").count(),
        "completed": db.session.query(PushJob).filter_by(status="completed").count(),
        "failed": db.session.query(PushJob).filter_by(status="failed").count(),
    }

    return render_template(
        "push_monitor.html",
        destinations=destinations,
        jobs=jobs,
        stats=stats,
        status_filter=status_filter,
    )


# ── Documentation Routes ─────────────────────────────────────


def _now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _get_capability_statement():
    """Get the current CapabilityStatement (from DB or default)."""
    from app.models.capability_statement import CapabilityStatement
    cs = db.session.query(CapabilityStatement).filter_by(is_current=True).first()
    if cs:
        return cs.resource_json
    from app.fhir.fhir_routes import _default_capability_statement
    return _default_capability_statement()


def _downloadable(html_content, filename):
    """Wrap rendered HTML in a download response."""
    response = make_response(html_content)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.route("/docs")
def docs_index():
    """Documentation index page."""
    return render_template("docs_index.html")


@bp.route("/docs/api")
def docs_api():
    """API endpoint reference."""
    return render_template("docs_api.html", generated=_now_str())


@bp.route("/docs/api/download")
def docs_api_download():
    """Download API reference as standalone HTML."""
    html = render_template("docs_api.html", generated=_now_str())
    return _downloadable(html, "ips_api_reference.html")


@bp.route("/docs/capability")
def docs_capability():
    """FHIR CapabilityStatement viewer."""
    cs = _get_capability_statement()
    cs_json = json.dumps(cs, indent=2)
    return render_template("docs_capability.html", cs=cs, cs_json=cs_json)


@bp.route("/docs/capability/download")
def docs_capability_download():
    """Download Capability Statement as standalone HTML."""
    cs = _get_capability_statement()
    cs_json = json.dumps(cs, indent=2)
    html = render_template("docs_capability.html", cs=cs, cs_json=cs_json)
    return _downloadable(html, "ips_capability_statement.html")


@bp.route("/docs/manual")
def docs_manual():
    """Operator manual."""
    return render_template("docs_manual.html", generated=_now_str())


@bp.route("/docs/manual/download")
def docs_manual_download():
    """Download operator manual as standalone HTML."""
    html = render_template("docs_manual.html", generated=_now_str())
    return _downloadable(html, "ips_operator_manual.html")


@bp.route("/docs/technical")
def docs_technical():
    """Technical documentation."""
    return render_template("docs_technical.html", generated=_now_str())


@bp.route("/docs/technical/download")
def docs_technical_download():
    """Download technical docs as standalone HTML."""
    html = render_template("docs_technical.html", generated=_now_str())
    return _downloadable(html, "ips_technical_documentation.html")
