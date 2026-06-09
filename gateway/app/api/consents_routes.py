"""Patient-consent REST surface — IPS Renov 2 (ticket #198).

Cohesive-care consent under Lag (2022:913) § 5. Peer to blocks_routes;
co-located access pattern, co-located audit pipeline.

    POST   /api/v1/patients/<guid>/consents                       — grant
    GET    /api/v1/patients/<guid>/consents?active=true           — list
    POST   /api/v1/patients/<guid>/consents/<cguid>/revoke        — revoke

Authorisation mirrors blocks_routes:

  - SU admin → unrestricted
  - Staff with a ``PatientClinicAssignment`` to the patient →
    grant / list / revoke
  - Other authenticated users → 403

The patient-self path (vårdnadshavare exclusion already noted in
blocks_routes) belongs to IPS Renov 3 / #199 and isn't reachable from
this surface yet.

Consumer enforcement (request.pdhc dispatch, cdr_6 cross-caregiver
reads) lives outside this module — those consumers fetch active
consents and gate their own behaviour. See tickets #229, #200, #231.
"""
from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.models.base import db, utcnow
from app.models.patient_consent import (
    PatientConsent,
    CONSENT_GRANTED_VIA,
)
from app.models.patient_index import PatientIndex
from app.services.audit_service import log_event
from app.services.auth_service import require_auth


bp = Blueprint("consents_api", __name__, url_prefix="/api/v1/patients")


# ---------------------------------------------------------------------------
# Auth helpers — mirror blocks_routes
# ---------------------------------------------------------------------------

def _is_admin() -> bool:
    user = getattr(g, "current_user", None)
    return bool(user and getattr(user, "is_superuser", False))


def _can_act_on_patient(patient_guid) -> bool:
    if _is_admin():
        return True
    user = getattr(g, "current_user", None)
    if user is None:
        return False
    from app.models.clinic import UserClinicAssignment
    from app.models.patient_index import PatientClinicAssignment
    has = (
        db.session.query(PatientClinicAssignment.guid)
        .join(
            UserClinicAssignment,
            UserClinicAssignment.clinic_guid
            == PatientClinicAssignment.clinic_guid,
        )
        .filter(
            PatientClinicAssignment.patient_guid == patient_guid,
            UserClinicAssignment.user_guid == user.guid,
        )
        .first()
    )
    return has is not None


def _patient_or_404(patient_guid):
    try:
        guid_obj = UUID(str(patient_guid))
    except (ValueError, TypeError):
        return None
    return db.session.query(PatientIndex).filter_by(guid=guid_obj).first()


def _bad(message, code=400, extra=None):
    body = {"error": message}
    if extra:
        body.update(extra)
    return jsonify(body), code


def _parse_iso(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalise_concept_guids(raw):
    """Normalise a list of concept guid strings. Returns (guids, error)."""
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, "consented_concept_guids must be a list"
    if not raw:
        return None, "consented_concept_guids must be non-empty when provided"
    try:
        return [str(UUID(str(c))) for c in raw], None
    except (ValueError, TypeError):
        return None, "consented_concept_guids must all be valid UUIDs"


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------

@bp.route("/<patient_guid>/consents", methods=["POST"])
@require_auth
def create_consent(patient_guid):
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)
    if not _can_act_on_patient(patient.guid):
        return _bad(
            "Not authorised to grant consents for this patient", 403,
        )

    payload = request.get_json(silent=True) or {}
    grantee_raw = payload.get("grantee_caregiver_guid")
    if not grantee_raw:
        return _bad("grantee_caregiver_guid is required", 400)
    try:
        grantee = UUID(str(grantee_raw))
    except (ValueError, TypeError):
        return _bad(
            "grantee_caregiver_guid must be a valid UUID", 400,
        )

    granted_via = payload.get("granted_via", "portal")
    if granted_via not in CONSENT_GRANTED_VIA:
        return _bad(
            f"granted_via must be one of {CONSENT_GRANTED_VIA}", 400,
        )

    contract_guid = None
    contract_raw = payload.get("contract_guid")
    if contract_raw:
        try:
            contract_guid = UUID(str(contract_raw))
        except (ValueError, TypeError):
            return _bad("contract_guid must be a valid UUID", 400)

    expires_at = None
    expires_raw = payload.get("expires_at")
    if expires_raw:
        expires_at = _parse_iso(expires_raw)
        if expires_at is None:
            return _bad("expires_at must be ISO 8601", 400)

    concept_guids, ce = _normalise_concept_guids(
        payload.get("consented_concept_guids"),
    )
    if ce:
        return _bad(ce, 400)

    note = (payload.get("granted_note") or "").strip() or None

    # Reject duplicate active consent to the same grantee.
    existing = (
        db.session.query(PatientConsent)
        .filter_by(
            patient_guid=patient.guid,
            grantee_caregiver_guid=grantee,
        )
        .all()
    )
    for row in existing:
        if row.is_active():
            return _bad(
                "Active consent already exists for this "
                "(patient, grantee)",
                409,
                {"existing_consent_guid": str(row.guid)},
            )

    consent = PatientConsent(
        patient_guid=patient.guid,
        grantee_caregiver_guid=grantee,
        contract_guid=contract_guid,
        granted_via=granted_via,
        granted_by_user_guid=getattr(g.current_user, "guid", None),
        granted_note=note,
        expires_at=expires_at,
        consented_concept_guids=concept_guids,
    )
    db.session.add(consent)
    db.session.flush()

    log_event(
        event_type="consent.granted",
        patient_guid=patient.guid,
        resource_type="PatientConsent",
        resource_guid=consent.guid,
        detail={
            "grantee_caregiver_guid": str(grantee),
            "granted_via": granted_via,
            "contract_guid": (
                str(contract_guid) if contract_guid else None
            ),
            "expires_at": (
                expires_at.isoformat() if expires_at else None
            ),
            "consented_concept_guids": concept_guids,
            "note": note,
        },
    )
    db.session.commit()
    return jsonify(consent.to_dict()), 201


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@bp.route("/<patient_guid>/consents", methods=["GET"])
@require_auth
def list_consents(patient_guid):
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)
    if not _can_act_on_patient(patient.guid):
        return _bad(
            "Not authorised to view consents for this patient", 403,
        )

    active_only = request.args.get("active", "true").lower() in (
        "true", "1", "yes",
    )
    rows = (
        db.session.query(PatientConsent)
        .filter_by(patient_guid=patient.guid)
        .order_by(PatientConsent.granted_at.desc())
        .all()
    )
    if active_only:
        rows = [r for r in rows if r.is_active()]

    return jsonify({
        "items": [r.to_dict() for r in rows],
        "total": len(rows),
    }), 200


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------

@bp.route(
    "/<patient_guid>/consents/<consent_guid>/revoke",
    methods=["POST"],
)
@require_auth
def revoke_consent(patient_guid, consent_guid):
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)
    if not _can_act_on_patient(patient.guid):
        return _bad(
            "Not authorised to revoke consents for this patient", 403,
        )

    try:
        consent_guid_obj = UUID(str(consent_guid))
    except (ValueError, TypeError):
        return _bad("Invalid consent_guid", 404)

    consent = (
        db.session.query(PatientConsent)
        .filter_by(guid=consent_guid_obj, patient_guid=patient.guid)
        .first()
    )
    if consent is None:
        return _bad("Consent not found", 404)
    if not consent.is_active():
        return _bad("Consent is already inactive (revoked or expired)", 409)

    payload = request.get_json(silent=True) or {}
    reason = (payload.get("reason") or "").strip() or None

    consent.revoked_at = utcnow()
    consent.revoked_by_user_guid = getattr(g.current_user, "guid", None)
    consent.revoked_reason = reason
    db.session.flush()

    log_event(
        event_type="consent.revoked",
        patient_guid=patient.guid,
        resource_type="PatientConsent",
        resource_guid=consent.guid,
        detail={
            "grantee_caregiver_guid": str(consent.grantee_caregiver_guid),
            "reason": reason,
        },
    )
    db.session.commit()
    return jsonify(consent.to_dict()), 200
