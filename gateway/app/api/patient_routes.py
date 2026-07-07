"""Patient-centric query routes.

Today this blueprint only carries the inverse of
`GET /api/v1/clinics/<guid>/patients` — i.e. given a patient, return
the clinics they are assigned to. Future patient-portal routes
(self-block management, self-consent — IPS Renov tickets #199 / #200)
will mount here too.
"""
from flask import Blueprint, jsonify, request

from app.models.base import db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import require_auth
from app.services.consent_policy import evaluate_patient

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


@bp.route("/analysis-filter", methods=["POST"])
@require_auth
def analysis_filter():
    """Apply the canonical analysis consent policy (#422) to a set of patients.

    ips owns the D1 consent flags, so it owns the enforcement: analysis
    services (analyse.pdhc, rosetta, cdr2-6) POST the candidate patient guids +
    their read context here and receive back only the patients they may read,
    plus the reason each excluded patient was dropped.

    Body:
        {
          "patient_guids": ["...", ...],
          "purpose": "research" | "statistics" | "quality_registry" | ...,
          "research_project_guids": ["...", ...]   # reader's affiliation projects
        }

    Returns:
        {
          "purpose": "...",
          "allowed": ["...guids..."],
          "excluded": [{"patient_guid": "...", "reason": "ehds_opt_out" | ...}]
        }
    """
    data = request.get_json(silent=True) or {}
    guids = data.get("patient_guids") or []
    purpose = (data.get("purpose") or "").strip()
    reader_projects = data.get("research_project_guids") or []

    if not purpose:
        return jsonify({"error": "purpose is required"}), 400
    if not isinstance(guids, list):
        return jsonify({"error": "patient_guids must be a list"}), 400

    # Load flags for the patients we know about; unknown guids get empty flags
    # (opt-outs default False; research consent empty -> excluded from research).
    rows = (
        db.session.query(PatientIndex)
        .filter(PatientIndex.guid.in_(guids))
        .all()
    ) if guids else []
    flags_by_guid = {
        str(p.guid): {
            "ehds_opt_out": p.ehds_opt_out,
            "quality_registry_opt_out": p.quality_registry_opt_out,
            "consented_research_projects": p.consented_research_projects or [],
        }
        for p in rows
    }

    allowed = []
    excluded = []
    for g in guids:
        ok, reason = evaluate_patient(
            flags_by_guid.get(str(g), {}), purpose, reader_projects)
        if ok:
            allowed.append(g)
        else:
            excluded.append({"patient_guid": g, "reason": reason})

    return jsonify({
        "purpose": purpose,
        "allowed": allowed,
        "excluded": excluded,
    })
