"""Care-access check + nödöppning endpoints (D3 #406).

Two operations on the composed zone rule (care_access_policy):

  POST /api/v1/patients/<guid>/care-access-check
      Evaluate one read: reader context × authoring context × the
      patient's active blocks, cohesive-care consents, and any live
      emergency grant. Returns {allowed, zone, access_basis, reason}.
      Every check is audited with the X1 tuple fields (purpose=care,
      access_basis) in detail — including denials.

  POST /api/v1/patients/<guid>/emergency-access
      Nödöppning (PDL 6 kap 5 §): create an attested, time-bound
      EmergencyAccess grant for the READING unit. Role-gated like the
      indispensable lift (SU or IPS_INDISPENSABLE_LIFT_ROLES), requires
      an explicit attestation flag + a written reason, audits with
      access_basis=emergency, and surfaces to the patient (portal
      banner + audit trail). The grant is INSERT-only and expires.
"""
import os
from datetime import datetime, timezone, timedelta

from flask import Blueprint, current_app, g, jsonify, request

from app.models.base import db
from app.models.patient_index import PatientIndex
from app.models.patient_block import PatientBlock
from app.models.patient_consent import PatientConsent
from app.models.emergency_access import (
    DEFAULT_EMERGENCY_ACCESS_SECONDS,
    EmergencyAccess,
)
from app.services.audit_service import log_event
from app.services.auth_service import require_auth
from app.services.care_access_policy import evaluate_care_access

bp = Blueprint("care_access_api", __name__, url_prefix="/api/v1/patients")


def _allowed_roles() -> set:
    """Nödöppning uses the same role gate as the indispensable lift —
    override with IPS_EMERGENCY_ACCESS_ROLES to split them later."""
    raw = (
        current_app.config.get("IPS_EMERGENCY_ACCESS_ROLES")
        or os.environ.get("IPS_EMERGENCY_ACCESS_ROLES")
        or current_app.config.get("IPS_INDISPENSABLE_LIFT_ROLES")
        or os.environ.get("IPS_INDISPENSABLE_LIFT_ROLES")
        or "physician,admin"
    )
    return {r.strip() for r in raw.split(",") if r.strip()}


def _is_physician_or_su(user) -> bool:
    if user is None:
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", "") in _allowed_roles()


def _bad(message, code=400):
    return jsonify({"error": message}), code


def _patient_or_404(patient_guid):
    return db.session.query(PatientIndex).filter_by(
        guid=patient_guid).one_or_none()


def _active_blocks(patient_guid):
    rows = db.session.query(PatientBlock).filter_by(
        patient_guid=patient_guid).all()
    return [b for b in rows if b.is_active()]


def _has_sharing_consent(patient_guid, reader_caregiver_guid) -> bool:
    if not reader_caregiver_guid:
        return False
    rows = db.session.query(PatientConsent).filter_by(
        patient_guid=patient_guid,
        grantee_caregiver_guid=reader_caregiver_guid).all()
    return any(c.is_active() for c in rows)


def _active_emergency(patient_guid, reader_unit_guid):
    if not reader_unit_guid:
        return None
    rows = db.session.query(EmergencyAccess).filter_by(
        patient_guid=patient_guid,
        reader_care_unit_guid=reader_unit_guid).all()
    live = [e for e in rows if e.is_active()]
    live.sort(key=lambda e: e.expires_at, reverse=True)
    return live[0] if live else None


@bp.route("/<patient_guid>/care-access-check", methods=["POST"])
@require_auth
def care_access_check(patient_guid):
    """Evaluate the composed zone rule for one read."""
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("patient not found", 404)

    body = request.get_json(silent=True) or {}
    reader_unit = (body.get("reader_care_unit_guid") or "").strip()
    reader_org = (body.get("reader_care_organisation_guid") or "").strip()
    author_clinic = (body.get("author_clinic_guid") or "").strip()
    author_caregiver = (body.get("author_caregiver_guid") or "").strip()
    if not reader_unit or not author_clinic:
        return _bad("reader_care_unit_guid and author_clinic_guid required")

    emergency = _active_emergency(patient.guid, reader_unit)
    allowed, zone, basis, reason = evaluate_care_access(
        reader_care_unit_guid=reader_unit,
        reader_care_organisation_guid=reader_org or None,
        author_clinic_guid=author_clinic,
        author_caregiver_guid=author_caregiver or None,
        active_blocks=_active_blocks(patient.guid),
        has_sharing_consent=_has_sharing_consent(patient.guid, reader_org),
        emergency_active=emergency is not None,
    )

    # X1-shaped audit — denials too: a refused read is PDL-relevant.
    log_event(
        "care_access.check",
        patient_guid=patient.guid,
        resource_type="CareAccessCheck",
        detail={
            "purpose": "care",
            "access_basis": basis,
            "allowed": allowed,
            "zone": zone,
            "reason": reason,
            "reader_care_unit_guid": reader_unit,
            "reader_care_organisation_guid": reader_org or None,
            "author_clinic_guid": author_clinic,
            "author_caregiver_guid": author_caregiver or None,
            "emergency_access_guid": (str(emergency.guid)
                                      if emergency else None),
        },
    )
    db.session.commit()

    return jsonify({
        "patient_guid": str(patient.guid),
        "allowed": allowed,
        "zone": zone,
        "access_basis": basis,
        "reason": reason,
        "emergency_access_guid": str(emergency.guid) if emergency else None,
    }), 200


@bp.route("/<patient_guid>/emergency-access", methods=["POST"])
@require_auth
def create_emergency_access(patient_guid):
    """Nödöppning — attested, time-bound, role-gated, audited."""
    if not _is_physician_or_su(getattr(g, "current_user", None)):
        return _bad(
            "Not authorised: nödöppning requires SU admin or a role in "
            "IPS_EMERGENCY_ACCESS_ROLES", 403)

    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("patient not found", 404)

    body = request.get_json(silent=True) or {}
    reader_unit = (body.get("reader_care_unit_guid") or "").strip()
    reader_org = (body.get("reader_care_organisation_guid") or "").strip()
    reason = (body.get("reason") or "").strip()
    attest = body.get("attest") is True

    if not reader_unit:
        return _bad("reader_care_unit_guid required")
    if not reason:
        return _bad("a written reason is required (PDL 6 kap 5 § — the "
                    "situation must be documented)")
    if not attest:
        return _bad("explicit attestation required: set attest=true to "
                    "confirm an acute situation where the patient's life "
                    "or health is at risk")

    expires_in = body.get("expires_in")
    try:
        expires_in = int(expires_in) if expires_in is not None \
            else DEFAULT_EMERGENCY_ACCESS_SECONDS
    except (TypeError, ValueError):
        return _bad("expires_in must be an integer number of seconds")
    if expires_in <= 0 or expires_in > 7 * 24 * 3600:
        return _bad("expires_in must be between 1 second and 7 days")

    actor = getattr(g, "current_user", None)
    now = datetime.now(timezone.utc)
    grant = EmergencyAccess(
        patient_guid=patient.guid,
        reader_care_unit_guid=reader_unit,
        reader_care_organisation_guid=reader_org or None,
        actor_user_guid=getattr(actor, "guid", None),
        actor_label=(getattr(actor, "display_name", None)
                     or getattr(actor, "username", None)),
        reason=reason,
        attested_at=now,
        expires_at=now + timedelta(seconds=expires_in),
        session_id=None,  # mirrored from the audit row below
    )
    db.session.add(grant)
    db.session.flush()

    entry = log_event(
        "emergency_access.granted",
        patient_guid=patient.guid,
        resource_type="EmergencyAccess",
        resource_guid=grant.guid,
        detail={
            "purpose": "care",
            "access_basis": "emergency",
            "reader_care_unit_guid": reader_unit,
            "reader_care_organisation_guid": reader_org or None,
            "reason": reason,
            "attested": True,
            "expires_at": grant.expires_at.isoformat(),
        },
    )
    grant.session_id = entry.session_id
    db.session.commit()

    return jsonify(grant.to_dict()), 201
