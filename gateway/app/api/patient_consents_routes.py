"""Patient-portal consent-management surface — IPS Renov 4 (ticket #200).

Peer to :mod:`patient_blocks_routes` and the staff equivalent
:mod:`consents_routes`. The patient acts directly on her own
``PatientConsent`` rows from the portal; identity comes from the SSO
blob via :func:`require_patient`, not from a URL segment.

Endpoints:

    GET    /api/v1/patient/consents                       — list own active consents
    POST   /api/v1/patient/consents                       — grant a consent
    POST   /api/v1/patient/consents/<consent_guid>/revoke — revoke

Differences vs. the staff endpoint:

  - ``granted_via`` is always ``"portal"`` here — the patient is
    granting via the portal by definition. Callers may not override
    it.
  - ``granted_by_user_guid`` is the patient's own ``patient_guid``
    (parity with :mod:`patient_blocks_routes`).
  - Cross-patient revoke attempts return 404, not 403, so consent
    existence is not leaked across patient_guid boundaries.

Audit rows carry ``actor_type='patient'``, ``actor_guid=patient_guid``,
and ``detail.mechanism='consent'`` so the PDL kontroller view can
filter "patient acted on her own data" the same way as the block side
(#199).
"""
from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.models.base import db, utcnow
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientIndex
from app.services.auth_service import require_patient


bp = Blueprint(
    "patient_consents_api", __name__,
    url_prefix="/api/v1/patient/consents",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bad(message, code=400, extra=None):
    body = {"error": message}
    if extra:
        body.update(extra)
    return jsonify(body), code


def _patient_or_404(patient_guid):
    try:
        guid_obj = UUID(str(patient_guid))
    except (ValueError, TypeError):
        return None
    return db.session.query(PatientIndex).filter_by(guid=guid_obj).first()


def _own_consent_or_404(consent_guid, patient_guid):
    try:
        consent_guid_obj = UUID(str(consent_guid))
        patient_guid_obj = UUID(str(patient_guid))
    except (ValueError, TypeError):
        return None
    return (
        db.session.query(PatientConsent)
        .filter_by(guid=consent_guid_obj, patient_guid=patient_guid_obj)
        .first()
    )


def _parse_iso(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalise_concept_guids(raw):
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


def _patient_audit(event_type, *, consent, detail_extra=None):
    """Write an audit row with the patient as actor."""
    base = {
        "mechanism": "consent",
        "consent_guid": str(consent.guid),
        "grantee_caregiver_guid": str(consent.grantee_caregiver_guid),
    }
    if detail_extra:
        base.update(detail_extra)

    from app.models.audit_log import AuditLog
    entry = AuditLog(
        actor_guid=UUID(str(g.patient_guid)),
        actor_type="patient",
        actor_label=f"patient:{g.patient_guid}",
        patient_guid=UUID(str(g.patient_guid)),
        event_type=event_type,
        resource_type="PatientConsent",
        resource_guid=consent.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        session_id=(
            g.access_blob.get("session_id")
            if isinstance(getattr(g, "access_blob", None), dict)
            else None
        ),
        detail=base,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


# ---------------------------------------------------------------------------
# GET — list own consents
# ---------------------------------------------------------------------------

@bp.route("", methods=["GET"])
@require_patient
def list_own_consents():
    patient = _patient_or_404(g.patient_guid)
    if patient is None:
        return _bad("Patient record not found in IPS", 404)

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
# POST — grant a consent on self
# ---------------------------------------------------------------------------

@bp.route("", methods=["POST"])
@require_patient
def grant_own_consent():
    patient = _patient_or_404(g.patient_guid)
    if patient is None:
        return _bad("Patient record not found in IPS", 404)

    payload = request.get_json(silent=True) or {}
    grantee_raw = payload.get("grantee_caregiver_guid")
    if not grantee_raw:
        return _bad("grantee_caregiver_guid is required", 400)
    try:
        grantee = UUID(str(grantee_raw))
    except (ValueError, TypeError):
        return _bad("grantee_caregiver_guid must be a valid UUID", 400)

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
                "Active consent already exists for this (patient, grantee)",
                409,
                {"existing_consent_guid": str(row.guid)},
            )

    consent = PatientConsent(
        patient_guid=patient.guid,
        grantee_caregiver_guid=grantee,
        granted_via="portal",
        granted_by_user_guid=patient.guid,
        granted_note=note,
        expires_at=expires_at,
        consented_concept_guids=concept_guids,
    )
    db.session.add(consent)
    db.session.flush()

    _patient_audit(
        "consent.granted",
        consent=consent,
        detail_extra={
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
# POST /<consent_guid>/revoke
# ---------------------------------------------------------------------------

@bp.route("/<consent_guid>/revoke", methods=["POST"])
@require_patient
def revoke_own_consent(consent_guid):
    consent = _own_consent_or_404(consent_guid, g.patient_guid)
    if consent is None:
        # 404 (not 403) so consent existence isn't leaked across
        # patient_guid boundaries — same confused-deputy guard as
        # patient_blocks_routes.lift_own_block.
        return _bad("Consent not found", 404)
    if not consent.is_active():
        return _bad("Consent is already inactive (revoked or expired)", 409)

    payload = request.get_json(silent=True) or {}
    reason = (payload.get("reason") or "").strip() or None

    consent.revoked_at = utcnow()
    consent.revoked_by_user_guid = UUID(str(g.patient_guid))
    consent.revoked_reason = reason
    db.session.flush()

    _patient_audit(
        "consent.revoked",
        consent=consent,
        detail_extra={"reason": reason},
    )
    db.session.commit()
    return jsonify(consent.to_dict()), 200
