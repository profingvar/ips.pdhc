"""Clinic management routes."""

import uuid

from flask import Blueprint, jsonify, request

from app.models.base import db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import require_auth
from app.services.audit_service import log_event
from app.services.fhir_service import create_resource

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


@bp.route("/<guid>/patients", methods=["POST"])
@require_auth
def create_clinic_patient(guid):
    """Programmatic create-patient endpoint for cross-service imports.

    Companion to the admin form `create_patient` — same effect
    (PatientIndex + PatientClinicAssignment row), but driven by JSON
    instead of HTML form data. Used by sim.pdhc's Synthea importer
    (Shape C of the synthea hookup proposal): the importer maps each
    Synthea Patient bundle to one POST here, the patient lands in
    ips.pdhc with a clinic assignment, and the next Cohort Builder
    run sees them in the roster.

    Request body — minimal shape::

        {
          "family_name": "Lindberg",
          "given_name":  "Olof",
          "gender":      "male",      # optional
          "birth_date":  "1948-09-18",  # optional, ISO date
          "identifier_system": "...",   # optional
          "identifier_value":  "...",   # optional, system-level identifier
        }

    Alternatively, pass a full FHIR Patient resource under "fhir":

        {"fhir": {"resourceType": "Patient", "name": [...], ...}}

    The endpoint normalises both shapes into a FHIR Patient resource,
    saves it (which `_sync_patient_index` then materialises into the
    PatientIndex row), and INSERTs a PatientClinicAssignment row
    against the URL's clinic guid.

    Returns the created PatientIndex dict + 201.
    """
    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    data = request.get_json(silent=True) or {}

    # If a full FHIR Patient was supplied, accept it; otherwise build
    # one from the flat fields.
    if "fhir" in data and isinstance(data["fhir"], dict):
        patient_fhir = dict(data["fhir"])
        if patient_fhir.get("resourceType") != "Patient":
            return jsonify({
                "error": "fhir.resourceType must be 'Patient'",
            }), 400
        # Ensure an id is present — _sync_patient_index keys on it.
        patient_fhir.setdefault("id", str(uuid.uuid4()))
    else:
        family = (data.get("family_name") or "").strip()
        given = (data.get("given_name") or "").strip()
        if not family or not given:
            return jsonify({
                "error": "family_name and given_name are required "
                         "(or supply a complete fhir.Patient body)",
            }), 400
        resource_id = str(uuid.uuid4())
        patient_fhir = {
            "resourceType": "Patient",
            "id": resource_id,
            "name": [{
                "use": "official",
                "family": family,
                "given": [given],
            }],
            "gender": (data.get("gender") or "unknown"),
        }
        if data.get("birth_date"):
            patient_fhir["birthDate"] = data["birth_date"]
        if data.get("identifier_value"):
            patient_fhir["identifier"] = [{
                "system": data.get("identifier_system")
                          or "urn:oid:1.2.752.129.2.1.3.1",
                "value": data["identifier_value"],
            }]
        if clinic.organisation_guid:
            patient_fhir["managingOrganization"] = {
                "reference": f"Organization/{clinic.organisation_guid}",
                "display": clinic.name,
            }

    create_resource("Patient", patient_fhir)
    pi = (
        db.session.query(PatientIndex)
        .filter_by(resource_id=patient_fhir["id"])
        .first()
    )
    if pi is None:
        # _sync_patient_index didn't populate PatientIndex — something
        # is wrong with the FHIR body (e.g., no name).
        db.session.rollback()
        return jsonify({
            "error": "PatientIndex was not created from the supplied FHIR; "
                     "the resource probably lacks the required fields (name).",
        }), 400

    db.session.add(PatientClinicAssignment(
        patient_guid=pi.guid,
        clinic_guid=clinic.guid,
    ))
    log_event("clinic_patient_create", resource_guid=pi.guid)
    db.session.commit()
    return jsonify(pi.to_dict()), 201
