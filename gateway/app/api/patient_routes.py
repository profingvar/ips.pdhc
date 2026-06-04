"""Patient-centric query routes.

Today this blueprint only carries the inverse of
`GET /api/v1/clinics/<guid>/patients` — i.e. given a patient, return
the clinics they are assigned to. Future patient-portal routes
(self-block management, self-consent — IPS Renov tickets #199 / #200)
will mount here too.
"""
from flask import Blueprint, jsonify

from app.models.base import db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import require_auth

bp = Blueprint("patient_api", __name__, url_prefix="/api/v1/patients")


@bp.route("/<guid>/clinics", methods=["GET"])
@require_auth
def list_patient_clinics(guid):
    """List active clinics a patient is assigned to.

    Used by request.pdhc (and other downstream services) to enforce
    patient-org need-to-know at write-side endpoints — see PDL
    Ch 4 §§ 1-2 and ticket #225.

    Returns the Clinic.to_dict() shape, ordered by name. Empty list
    when the patient exists but has no assignments. 404 when the
    patient does not exist.
    """
    patient = db.session.query(PatientIndex).filter_by(guid=guid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    clinics = (
        db.session.query(Clinic)
        .join(
            PatientClinicAssignment,
            PatientClinicAssignment.clinic_guid == Clinic.guid,
        )
        .filter(PatientClinicAssignment.patient_guid == patient.guid)
        .filter(Clinic.is_active.is_(True))
        .order_by(Clinic.name)
        .all()
    )
    return jsonify([c.to_dict() for c in clinics])
