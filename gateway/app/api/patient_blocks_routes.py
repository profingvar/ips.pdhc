"""Patient-portal block-management surface — IPS Renov 3 (ticket #199).

The patient acts directly on her own ``PatientBlock`` rows from the
patient portal. Distinct from ``blocks_routes`` (which is the staff /
admin path under ``/api/v1/patients/<patient_guid>/blocks``) in two
ways:

  - **Patient identity comes from the SSO blob**, not from a URL
    segment. The patient cannot act on someone else's blocks via this
    surface — the ``patient_guid`` is read off ``g.patient_guid`` set
    by :func:`require_patient`. There is no URL-side ``<patient_guid>``
    parameter to manipulate.
  - **Lifts are plain "consent" lifts** (spärr plan § 8.1, PDL Ch 4 § 5
    second clause). They don't carry the mechanical filter required for
    indispensable-care lifts, and they don't auto-re-impose — the patient
    is consenting outright.

Endpoints:

    GET    /api/v1/patient/blocks                       — list own active blocks
    POST   /api/v1/patient/blocks                       — block a source
    POST   /api/v1/patient/blocks/<block_guid>/lift     — own-consent lift
    POST   /api/v1/patient/blocks/<block_guid>/extend   — push expires_at forward

Audit rows carry ``actor_type='patient'``, ``actor_guid=<patient_guid>``,
and ``detail.mechanism='consent'`` so the PDL kontroller view can
filter "all actions taken by this patient on her own data" in one
query.

Vårdnadshavare exception — note in plan § 8.1: a parent-on-child act
is NOT reachable from this surface; it must go through the staff /
admin endpoint with a clinic relationship. The check here is
``g.patient_guid == block.patient_guid`` and nothing else.
"""
from datetime import timedelta
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.models.base import db, utcnow
from app.models.clinic import Clinic
from app.models.patient_block import (
    PatientBlock,
    BLOCK_SCOPE_TYPES,
)
from app.models.patient_index import PatientIndex
from app.services.audit_service import log_event
from app.services.auth_service import require_patient
from app.services.block_webhook import safe_dispatch as _emit_block_webhook


bp = Blueprint(
    "patient_blocks_api", __name__, url_prefix="/api/v1/patient/blocks"
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


def _own_block_or_404(block_guid, patient_guid):
    try:
        block_guid_obj = UUID(str(block_guid))
        patient_guid_obj = UUID(str(patient_guid))
    except (ValueError, TypeError):
        return None
    return (
        db.session.query(PatientBlock)
        .filter_by(guid=block_guid_obj, patient_guid=patient_guid_obj)
        .first()
    )


def _patient_audit(event_type, *, block, mechanism, detail_extra=None):
    """Wrapper around :func:`log_event` that fills the patient-actor
    fields explicitly — :func:`log_event` reads ``g.current_user`` which
    is None on patient-portal calls."""
    base = {
        "mechanism": mechanism,
        "block_guid": str(block.guid),
        "source_scope_type": block.source_scope_type,
        "source_scope_id": str(block.source_scope_id),
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
        resource_type="PatientBlock",
        resource_guid=block.guid,
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


def _parse_iso(s):
    from datetime import datetime as _dt
    if not isinstance(s, str):
        return None
    try:
        return _dt.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# GET — list own active blocks
# ---------------------------------------------------------------------------

@bp.route("", methods=["GET"])
@require_patient
def list_own_blocks():
    patient = _patient_or_404(g.patient_guid)
    if patient is None:
        # SSO says you're patient P but P doesn't exist in IPS — usually
        # an SSO/IPS sync issue, not a malicious caller. 404 with a hint.
        return _bad("Patient record not found in IPS", 404)

    active_only = request.args.get("active", "true").lower() in (
        "true", "1", "yes",
    )
    rows = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=patient.guid)
        .order_by(PatientBlock.created_at.desc())
        .all()
    )
    if active_only:
        rows = [r for r in rows if r.is_active()]

    items = []
    for r in rows:
        d = r.to_dict()
        # The patient can see her own source-scope details unredacted —
        # no §5.2 "leak protection" needed when the patient herself is
        # the caller.
        if r.source_scope_type == "clinic":
            clinic = db.session.query(Clinic).filter_by(
                guid=r.source_scope_id
            ).first()
            if clinic:
                d["source_scope_name"] = clinic.name
        items.append(d)
    return jsonify({"items": items, "total": len(items)}), 200


# ---------------------------------------------------------------------------
# POST — create a block on self
# ---------------------------------------------------------------------------

@bp.route("", methods=["POST"])
@require_patient
def create_own_block():
    patient = _patient_or_404(g.patient_guid)
    if patient is None:
        return _bad("Patient record not found in IPS", 404)

    payload = request.get_json(silent=True) or {}
    scope_type = payload.get("source_scope_type", "clinic")
    scope_id_raw = payload.get("source_scope_id")
    reason = (payload.get("reason") or "").strip() or None

    if scope_type not in BLOCK_SCOPE_TYPES:
        return _bad(
            f"source_scope_type must be one of {BLOCK_SCOPE_TYPES}", 400
        )
    if not scope_id_raw:
        return _bad("source_scope_id is required", 400)
    try:
        scope_id = UUID(str(scope_id_raw))
    except (ValueError, TypeError):
        return _bad("source_scope_id must be a valid UUID", 400)

    if scope_type == "clinic":
        clinic = db.session.query(Clinic).filter_by(guid=scope_id).first()
        if clinic is None:
            return _bad(f"Clinic {scope_id_raw} not found", 404)

    expires_at = None
    expires_raw = payload.get("expires_at")
    if expires_raw:
        expires_at = _parse_iso(expires_raw)
        if expires_at is None:
            return _bad("expires_at must be ISO 8601", 400)

    existing = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=patient.guid, source_scope_id=scope_id)
        .all()
    )
    for row in existing:
        if row.is_active():
            return _bad(
                "Active block already exists for this (patient, source)",
                409,
                {"existing_block_guid": str(row.guid)},
            )

    block = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type=scope_type,
        source_scope_id=scope_id,
        created_by_user_guid=patient.guid,
        created_reason=reason,
        expires_at=expires_at,
    )
    db.session.add(block)
    db.session.flush()

    _patient_audit(
        "block.created",
        block=block,
        mechanism="consent",
        detail_extra={
            "reason": reason,
            "expires_at": (
                expires_at.isoformat() if expires_at else None
            ),
        },
    )
    db.session.commit()
    _emit_block_webhook("block.created", block)
    return jsonify(block.to_dict()), 201


# ---------------------------------------------------------------------------
# POST /<block_guid>/lift — consent lift
# ---------------------------------------------------------------------------

@bp.route("/<block_guid>/lift", methods=["POST"])
@require_patient
def lift_own_block(block_guid):
    block = _own_block_or_404(block_guid, g.patient_guid)
    if block is None:
        # 404 — do not distinguish "wrong patient" from "no such block"
        # at this surface; that distinction would be a confused-deputy
        # oracle (PDL §4 ¶3 "blocked data exists" disclosure is metadata
        # for the patient's OWN patient_guid, not for someone else's).
        return _bad("Block not found", 404)
    if not block.is_active():
        return _bad("Block is already lifted", 409)

    payload = request.get_json(silent=True) or {}
    reason = (payload.get("reason") or "").strip() or None

    # Patient self-lift is always "consent" (plan § 8.1) — staff lifting
    # with indispensable_care kind belongs to /api/v1/patients/<g>/blocks/.
    block.lifted_at = utcnow()
    block.lifted_by_user_guid = UUID(str(g.patient_guid))
    block.lifted_reason = reason
    block.lift_kind = "consent"
    block.lift_concept_guids = None
    block.lift_from_date = None
    block.lift_until_date = None
    block.lift_expires_at = None
    db.session.flush()

    _patient_audit(
        "block.lifted",
        block=block,
        mechanism="consent",
        detail_extra={"reason": reason, "lift_kind": "consent"},
    )
    db.session.commit()
    _emit_block_webhook("block.lifted", block)
    return jsonify(block.to_dict()), 200


# ---------------------------------------------------------------------------
# POST /<block_guid>/extend — push expires_at forward
# ---------------------------------------------------------------------------

@bp.route("/<block_guid>/extend", methods=["POST"])
@require_patient
def extend_own_block(block_guid):
    block = _own_block_or_404(block_guid, g.patient_guid)
    if block is None:
        return _bad("Block not found", 404)
    if not block.is_active():
        return _bad("Cannot extend a lifted block", 409)

    payload = request.get_json(silent=True) or {}
    new_expires_raw = payload.get("expires_at")
    extend_by_seconds_raw = payload.get("extend_by_seconds")

    if new_expires_raw and extend_by_seconds_raw:
        return _bad(
            "Provide exactly one of expires_at or extend_by_seconds", 400
        )

    new_expires_at = None
    if new_expires_raw:
        new_expires_at = _parse_iso(new_expires_raw)
        if new_expires_at is None:
            return _bad("expires_at must be ISO 8601", 400)
    elif extend_by_seconds_raw is not None:
        try:
            seconds = int(extend_by_seconds_raw)
        except (TypeError, ValueError):
            return _bad("extend_by_seconds must be an integer", 400)
        if seconds <= 0:
            return _bad("extend_by_seconds must be positive", 400)
        # Anchor on the current expires_at if any, else "now".
        anchor = block.expires_at or utcnow()
        # Normalise anchor to aware (SQLite returns naive).
        if anchor.tzinfo is None:
            from datetime import timezone as _tz
            anchor = anchor.replace(tzinfo=_tz.utc)
        new_expires_at = anchor + timedelta(seconds=seconds)
    else:
        # Lift the time-bound entirely — convert to open-ended.
        new_expires_at = None

    # Refuse to shrink the expiry below "now"; that's a lift, not an
    # extend. Require it be strictly in the future.
    if new_expires_at is not None and new_expires_at <= utcnow():
        return _bad(
            "expires_at must be in the future; use /lift to release a block",
            400,
        )

    prev_expires_at = block.expires_at
    block.expires_at = new_expires_at
    db.session.flush()

    _patient_audit(
        "block.extended",
        block=block,
        mechanism="consent",
        detail_extra={
            "previous_expires_at": (
                prev_expires_at.isoformat() if prev_expires_at else None
            ),
            "new_expires_at": (
                new_expires_at.isoformat() if new_expires_at else None
            ),
        },
    )
    db.session.commit()
    _emit_block_webhook("block.extended", block)
    return jsonify(block.to_dict()), 200
