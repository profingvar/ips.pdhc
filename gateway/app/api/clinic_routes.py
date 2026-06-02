"""Clinic management routes."""

from flask import Blueprint, jsonify, request

from app.models.base import db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import require_auth
from app.services.audit_service import log_event

bp = Blueprint("clinic_api", __name__, url_prefix="/api/v1/clinics")


@bp.route("", methods=["POST"])
@require_auth
def create_clinic():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    clinic = Clinic(
        name=data["name"],
        identifier=data.get("identifier"),
        organisation_guid=data.get("organisation_guid"),
    )
    db.session.add(clinic)
    log_event("clinic_create", resource_guid=clinic.guid)
    db.session.commit()
    return jsonify(clinic.to_dict()), 201


@bp.route("", methods=["GET"])
@require_auth
def list_clinics():
    clinics = db.session.query(Clinic).filter_by(is_active=True).order_by(Clinic.name).all()
    return jsonify([c.to_dict() for c in clinics])


@bp.route("/<guid>", methods=["GET"])
@require_auth
def get_clinic(guid):
    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404
    return jsonify(clinic.to_dict())


@bp.route("/<guid>", methods=["PATCH"])
@require_auth
def update_clinic(guid):
    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        clinic.name = data["name"]
    if "identifier" in data:
        clinic.identifier = data["identifier"]
    if "is_active" in data:
        clinic.is_active = data["is_active"]

    log_event("clinic_update", resource_guid=clinic.guid)
    db.session.commit()
    return jsonify(clinic.to_dict())


@bp.route("/<guid>/patients", methods=["GET"])
@require_auth
def list_clinic_patients(guid):
    """List active patients assigned to a clinic.

    Returns the same PatientIndex.to_dict() shape as the rest of the
    application API, ordered by (family_name, given_name). The join
    goes through PatientClinicAssignment; duplicates are impossible
    thanks to the (patient_guid, clinic_guid) unique constraint.
    """
    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    patients = (
        db.session.query(PatientIndex)
        .join(
            PatientClinicAssignment,
            PatientClinicAssignment.patient_guid == PatientIndex.guid,
        )
        .filter(PatientClinicAssignment.clinic_guid == clinic.guid)
        .filter(PatientIndex.is_active.is_(True))
        .order_by(PatientIndex.family_name, PatientIndex.given_name)
        .all()
    )
    return jsonify([p.to_dict() for p in patients])
