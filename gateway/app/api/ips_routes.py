"""Application API routes for IPS cards and snapshots."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.models.base import db
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.patient_index import PatientIndex
from app.services.auth_service import require_auth
from app.services.audit_service import log_event
from app.services.ips_generator import generate_ips_bundle
from flask import g

bp = Blueprint("ips_api", __name__, url_prefix="/api/v1/ips")


# ── IPS Cards ────────────────────────────────────────────────

@bp.route("/cards", methods=["POST"])
@require_auth
def create_card():
    """Create an IPS card for a patient."""
    data = request.get_json(silent=True) or {}
    patient_guid = data.get("patient_guid")
    if not patient_guid:
        return jsonify({"error": "patient_guid is required"}), 400

    patient = db.session.query(PatientIndex).filter_by(guid=patient_guid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    card = IpsCard(
        patient_guid=patient.guid,
        clinic_guid=data.get("clinic_guid"),
        created_by_guid=getattr(g.current_user, "guid", None),
        title=data.get("title", "International Patient Summary"),
        mode=data.get("mode", "full"),
    )
    db.session.add(card)
    log_event("ips_card_create", patient_guid=patient.guid, resource_guid=card.guid)
    db.session.commit()
    return jsonify(card.to_dict()), 201


@bp.route("/cards", methods=["GET"])
@require_auth
def list_cards():
    """List IPS cards, filterable by patient_guid and clinic_guid."""
    query = db.session.query(IpsCard)
    patient_guid = request.args.get("patient_guid")
    clinic_guid = request.args.get("clinic_guid")
    if patient_guid:
        query = query.filter_by(patient_guid=patient_guid)
    if clinic_guid:
        query = query.filter_by(clinic_guid=clinic_guid)
    cards = query.order_by(IpsCard.created_at.desc()).all()
    return jsonify([c.to_dict() for c in cards])


@bp.route("/cards/<guid>", methods=["GET"])
@require_auth
def get_card(guid):
    """Get a single IPS card."""
    card = db.session.query(IpsCard).filter_by(guid=guid).first()
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card.to_dict())


@bp.route("/cards/<guid>", methods=["PATCH"])
@require_auth
def update_card(guid):
    """Update an IPS card (status, mode, title)."""
    card = db.session.query(IpsCard).filter_by(guid=guid).first()
    if not card:
        return jsonify({"error": "Card not found"}), 404

    data = request.get_json(silent=True) or {}
    if "status" in data:
        card.status = data["status"]
    if "mode" in data:
        card.mode = data["mode"]
    if "title" in data:
        card.title = data["title"]

    log_event("ips_card_update", patient_guid=card.patient_guid, resource_guid=card.guid)
    db.session.commit()
    return jsonify(card.to_dict())


@bp.route("/cards/<guid>", methods=["DELETE"])
@require_auth
def archive_card(guid):
    """Archive an IPS card."""
    card = db.session.query(IpsCard).filter_by(guid=guid).first()
    if not card:
        return jsonify({"error": "Card not found"}), 404
    card.status = "archived"
    log_event("ips_card_archive", patient_guid=card.patient_guid, resource_guid=card.guid)
    db.session.commit()
    return jsonify(card.to_dict())


# ── IPS Snapshots ────────────────────────────────────────────

@bp.route("/cards/<guid>/snapshots", methods=["POST"])
@require_auth
def create_snapshot(guid):
    """Generate and store an IPS snapshot for a card."""
    card = db.session.query(IpsCard).filter_by(guid=guid).first()
    if not card:
        return jsonify({"error": "Card not found"}), 404

    patient = db.session.query(PatientIndex).filter_by(guid=card.patient_guid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    now = datetime.now(timezone.utc)
    bundle = generate_ips_bundle(patient, mode=card.mode, composition_date=now)

    snapshot = IpsSnapshot(
        card_guid=card.guid,
        bundle_json=bundle,
        composition_date=now,
        mode=card.mode,
        generated_by_guid=getattr(g.current_user, "guid", None),
        resource_count=len(bundle.get("entry", [])),
    )
    db.session.add(snapshot)
    log_event("ips_snapshot_create", patient_guid=patient.guid, resource_guid=snapshot.guid)
    db.session.commit()
    return jsonify(snapshot.to_dict()), 201


@bp.route("/cards/<guid>/snapshots", methods=["GET"])
@require_auth
def list_snapshots(guid):
    """List snapshots for a card."""
    card = db.session.query(IpsCard).filter_by(guid=guid).first()
    if not card:
        return jsonify({"error": "Card not found"}), 404
    snapshots = db.session.query(IpsSnapshot).filter_by(
        card_guid=card.guid
    ).order_by(IpsSnapshot.created_at.desc()).all()
    return jsonify([s.to_dict() for s in snapshots])


@bp.route("/snapshots/<guid>", methods=["GET"])
@require_auth
def get_snapshot(guid):
    """Get snapshot metadata."""
    snapshot = db.session.query(IpsSnapshot).filter_by(guid=guid).first()
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404
    return jsonify(snapshot.to_dict())


@bp.route("/snapshots/<guid>/bundle", methods=["GET"])
@require_auth
def get_snapshot_bundle(guid):
    """Get the full IPS bundle JSON — this is an audited read."""
    snapshot = db.session.query(IpsSnapshot).filter_by(guid=guid).first()
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    card = db.session.query(IpsCard).filter_by(guid=snapshot.card_guid).first()
    patient_guid = card.patient_guid if card else None

    log_event(
        "ips_bundle_read",
        patient_guid=patient_guid,
        resource_guid=snapshot.guid,
        detail={"mode": snapshot.mode},
    )
    db.session.commit()
    return jsonify(snapshot.bundle_json)
