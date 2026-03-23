"""Push destination and job management routes."""

from flask import Blueprint, jsonify, request, g

from app.models.base import db
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.ips_snapshot import IpsSnapshot
from app.services.auth_service import require_auth
from app.services.audit_service import log_event

bp = Blueprint("push_api", __name__, url_prefix="/api/v1/push")


# ── Push Destinations ────────────────────────────────────────

@bp.route("/destinations", methods=["POST"])
@require_auth
def create_destination():
    data = request.get_json(silent=True) or {}
    required = ["name", "destination_type", "endpoint_url"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    dest = PushDestination(
        name=data["name"],
        destination_type=data["destination_type"],
        endpoint_url=data["endpoint_url"],
        auth_method=data.get("auth_method"),
        auth_config=data.get("auth_config", {}),
        headers=data.get("headers", {}),
    )
    db.session.add(dest)
    log_event("push_destination_create", resource_guid=dest.guid)
    db.session.commit()
    return jsonify(dest.to_dict()), 201


@bp.route("/destinations", methods=["GET"])
@require_auth
def list_destinations():
    dests = db.session.query(PushDestination).filter_by(is_active=True).order_by(
        PushDestination.name
    ).all()
    return jsonify([d.to_dict() for d in dests])


@bp.route("/destinations/<guid>", methods=["GET"])
@require_auth
def get_destination(guid):
    dest = db.session.query(PushDestination).filter_by(guid=guid).first()
    if not dest:
        return jsonify({"error": "Destination not found"}), 404
    return jsonify(dest.to_dict())


@bp.route("/destinations/<guid>", methods=["PATCH"])
@require_auth
def update_destination(guid):
    dest = db.session.query(PushDestination).filter_by(guid=guid).first()
    if not dest:
        return jsonify({"error": "Destination not found"}), 404

    data = request.get_json(silent=True) or {}
    for field in ["name", "destination_type", "endpoint_url", "auth_method", "auth_config", "headers"]:
        if field in data:
            setattr(dest, field, data[field])

    log_event("push_destination_update", resource_guid=dest.guid)
    db.session.commit()
    return jsonify(dest.to_dict())


@bp.route("/destinations/<guid>", methods=["DELETE"])
@require_auth
def deactivate_destination(guid):
    dest = db.session.query(PushDestination).filter_by(guid=guid).first()
    if not dest:
        return jsonify({"error": "Destination not found"}), 404
    dest.is_active = False
    log_event("push_destination_deactivate", resource_guid=dest.guid)
    db.session.commit()
    return jsonify(dest.to_dict())


# ── Push Jobs ────────────────────────────────────────────────

@bp.route("/jobs", methods=["POST"])
@require_auth
def create_job():
    data = request.get_json(silent=True) or {}
    snapshot_guid = data.get("snapshot_guid")
    destination_guid = data.get("destination_guid")
    if not snapshot_guid or not destination_guid:
        return jsonify({"error": "snapshot_guid and destination_guid are required"}), 400

    snapshot = db.session.query(IpsSnapshot).filter_by(guid=snapshot_guid).first()
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    dest = db.session.query(PushDestination).filter_by(guid=destination_guid, is_active=True).first()
    if not dest:
        return jsonify({"error": "Destination not found or inactive"}), 404

    job = PushJob(
        snapshot_guid=snapshot.guid,
        destination_guid=dest.guid,
        initiated_by_guid=getattr(g.current_user, "guid", None),
    )
    db.session.add(job)
    log_event("push_job_create", resource_guid=job.guid)
    db.session.commit()
    return jsonify(job.to_dict()), 201


@bp.route("/jobs", methods=["GET"])
@require_auth
def list_jobs():
    query = db.session.query(PushJob)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    jobs = query.order_by(PushJob.created_at.desc()).all()
    return jsonify([j.to_dict() for j in jobs])


@bp.route("/jobs/<guid>", methods=["GET"])
@require_auth
def get_job(guid):
    job = db.session.query(PushJob).filter_by(guid=guid).first()
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job.to_dict())
