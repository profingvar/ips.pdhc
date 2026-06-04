"""Patient-block REST surface — spärr Phase 1 (ticket #197).

Implements the PDL Ch 4 § 4 right to block, per
analysis/sparr_implementation_plan.md §§ 5–6:

    POST   /api/v1/patients/<guid>/blocks                  — create
    GET    /api/v1/patients/<guid>/blocks?active=true      — list
    POST   /api/v1/patients/<guid>/blocks/<bguid>/lift     — lift
    GET    /api/v1/patients/<guid>/blocks/metadata         — metadata
    (5.5 audit query reuses existing /api/v1/audit)

v1 authorisation: staff with a ``PatientClinicAssignment`` to the
patient OR SU admin. The plan's patient-self path and the
vårdnadshavare prohibition need a User↔PatientIndex link that doesn't
exist in ips today; they're tracked in IPS Renov 3 (#199 patient
portal) and aren't reachable until that link lands.
"""
from datetime import timedelta
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.models.base import db, utcnow
from app.models.clinic import Clinic
from app.models.patient_block import (
    PatientBlock,
    BLOCK_SCOPE_TYPES,
    BLOCK_LIFT_KINDS,
    _as_aware,
)
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.audit_service import log_event
from app.services.auth_service import require_auth


bp = Blueprint("blocks_api", __name__, url_prefix="/api/v1/patients")


# Default for indispensable_care lift (legal 2026-06-04 — 24h is
# explicitly allowed; consumers can override per-lift via expires_in).
DEFAULT_INDISPENSABLE_LIFT_SECONDS = 24 * 60 * 60


# ---------------------------------------------------------------------------
# Authorisation helpers
# ---------------------------------------------------------------------------

def _is_admin() -> bool:
    user = getattr(g, "current_user", None)
    return bool(user and getattr(user, "is_superuser", False))


def _can_act_on_patient(patient_guid) -> bool:
    """Authorisation gate for create / list / lift / metadata."""
    if _is_admin():
        return True
    user = getattr(g, "current_user", None)
    if user is None:
        return False
    # Staff with any clinic assignment to this patient.
    from app.models.clinic import UserClinicAssignment
    has = (
        db.session.query(PatientClinicAssignment.guid)
        .join(
            UserClinicAssignment,
            UserClinicAssignment.clinic_guid == PatientClinicAssignment.clinic_guid,
        )
        .filter(
            PatientClinicAssignment.patient_guid == patient_guid,
            UserClinicAssignment.user_guid == user.guid,
        )
        .first()
    )
    return has is not None


def _user_clinic_guids_set(user) -> set:
    from app.models.clinic import UserClinicAssignment
    rows = db.session.query(UserClinicAssignment.clinic_guid).filter(
        UserClinicAssignment.user_guid == user.guid
    ).all()
    return {r[0] for r in rows}


def _scope_visible_to_caller(block: PatientBlock) -> bool:
    """The plan §5.2 says a clinic-B user listing patient blocks should
    see "this patient has 1 block" but not "the block is on clinic A's
    data" unless they are at clinic A or admin. v1 surfaces the full
    list to anyone with ANY relationship to the patient and full
    details to admin; we omit source_scope_id when the caller's clinic
    set doesn't include it."""
    if _is_admin():
        return True
    user = getattr(g, "current_user", None)
    if user is None:
        return False
    return block.source_scope_id in _user_clinic_guids_set(user)


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


# ---------------------------------------------------------------------------
# 5.1 — Create block
# ---------------------------------------------------------------------------

@bp.route("/<patient_guid>/blocks", methods=["POST"])
@require_auth
def create_block(patient_guid):
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)
    if not _can_act_on_patient(patient.guid):
        return _bad("Not authorised to create blocks for this patient", 403)

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

    # Reject duplicate active block on the same (patient, scope_id).
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

    user = g.current_user
    block = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type=scope_type,
        source_scope_id=scope_id,
        created_by_user_guid=getattr(user, "guid", None),
        created_reason=reason,
    )
    db.session.add(block)
    db.session.flush()

    log_event(
        event_type="block.created",
        patient_guid=patient.guid,
        resource_type="PatientBlock",
        resource_guid=block.guid,
        detail={
            "source_scope_type": scope_type,
            "source_scope_id": str(scope_id),
            "reason": reason,
        },
    )
    db.session.commit()
    return jsonify(block.to_dict()), 201


# ---------------------------------------------------------------------------
# 5.2 — List blocks for a patient
# ---------------------------------------------------------------------------

@bp.route("/<patient_guid>/blocks", methods=["GET"])
@require_auth
def list_blocks(patient_guid):
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)
    if not _can_act_on_patient(patient.guid):
        return _bad("Not authorised to view blocks for this patient", 403)

    active_only = request.args.get("active", "true").lower() in ("true", "1", "yes")
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
        # Plan §5.2: don't leak source_scope_id to clients without the
        # right relationship. Admin sees all; others see only their own
        # clinic's blocks in detail. Surface scope-name too for UX.
        if not _scope_visible_to_caller(r):
            d["source_scope_id"] = None
            d.pop("created_reason", None)
            d.pop("created_by_user_guid", None)
            d["redacted"] = True
        else:
            d["redacted"] = False
            if r.source_scope_type == "clinic":
                clinic = db.session.query(Clinic).filter_by(
                    guid=r.source_scope_id
                ).first()
                if clinic:
                    d["source_scope_name"] = clinic.name
        items.append(d)
    return jsonify({"items": items, "total": len(items)}), 200


# ---------------------------------------------------------------------------
# 5.3 — Lift a block
# ---------------------------------------------------------------------------

@bp.route(
    "/<patient_guid>/blocks/<block_guid>/lift", methods=["POST"]
)
@require_auth
def lift_block(patient_guid, block_guid):
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)
    if not _can_act_on_patient(patient.guid):
        return _bad("Not authorised to lift blocks for this patient", 403)

    try:
        block_guid_obj = UUID(str(block_guid))
    except (ValueError, TypeError):
        return _bad("Invalid block_guid", 404)
    block = (
        db.session.query(PatientBlock)
        .filter_by(guid=block_guid_obj, patient_guid=patient.guid)
        .first()
    )
    if block is None:
        return _bad("Block not found", 404)
    if not block.is_active():
        return _bad("Block is already lifted", 404)

    payload = request.get_json(silent=True) or {}
    lift_kind = payload.get("lift_kind")
    reason = (payload.get("reason") or "").strip() or None

    if lift_kind not in BLOCK_LIFT_KINDS:
        return _bad(
            f"lift_kind must be one of {BLOCK_LIFT_KINDS}", 400
        )

    block.lifted_at = utcnow()
    block.lifted_by_user_guid = getattr(g.current_user, "guid", None)
    block.lifted_reason = reason
    block.lift_kind = lift_kind

    if lift_kind == "indispensable_care":
        # Legal 2026-06-04: mechanical filter REQUIRED.
        concept_guids = payload.get("concept_guids") or []
        if not isinstance(concept_guids, list) or not concept_guids:
            return _bad(
                "concept_guids is required for indispensable_care lift "
                "(legal 2026-06-04: mechanical filter required)",
                400,
            )
        if not reason:
            return _bad(
                "reason is required for indispensable_care lift",
                400,
            )
        # Validate concept_guid shape — accept strings; do not validate
        # against plan.pdhc here (that's an Renov 6 / federation
        # concern). Normalise to strings.
        try:
            normalised = [str(UUID(str(c))) for c in concept_guids]
        except (ValueError, TypeError):
            return _bad("concept_guids must all be valid UUIDs", 400)
        block.lift_concept_guids = normalised

        expires_in = int(payload.get("expires_in") or
                         DEFAULT_INDISPENSABLE_LIFT_SECONDS)
        if expires_in <= 0:
            return _bad("expires_in must be a positive number of seconds", 400)
        block.lift_expires_at = utcnow() + timedelta(seconds=expires_in)

        from_date_raw = payload.get("from_date")
        until_date_raw = payload.get("until_date")
        if from_date_raw:
            block.lift_from_date = _parse_iso(from_date_raw)
            if block.lift_from_date is None:
                return _bad("from_date must be ISO 8601", 400)
        if until_date_raw:
            block.lift_until_date = _parse_iso(until_date_raw)
            if block.lift_until_date is None:
                return _bad("until_date must be ISO 8601", 400)
    else:
        # consent lift — leave mechanical-filter columns NULL; no
        # auto-re-block (lift_expires_at stays NULL → permanent).
        block.lift_concept_guids = None
        block.lift_from_date = None
        block.lift_until_date = None
        block.lift_expires_at = None

    db.session.flush()

    log_event(
        event_type="block.lifted",
        patient_guid=patient.guid,
        resource_type="PatientBlock",
        resource_guid=block.guid,
        detail={
            "lift_kind": lift_kind,
            "reason": reason,
            "lift_expires_at": (
                block.lift_expires_at.isoformat()
                if block.lift_expires_at else None
            ),
            "lift_concept_guids": block.lift_concept_guids,
            "lift_from_date": (
                block.lift_from_date.isoformat()
                if block.lift_from_date else None
            ),
            "lift_until_date": (
                block.lift_until_date.isoformat()
                if block.lift_until_date else None
            ),
        },
    )
    db.session.commit()
    return jsonify(block.to_dict()), 200


# ---------------------------------------------------------------------------
# 5.4 — Metadata-only ("blocked data exists")
# ---------------------------------------------------------------------------

@bp.route("/<patient_guid>/blocks/metadata", methods=["GET"])
@require_auth
def block_metadata(patient_guid):
    """Legal 2026-06-04: this metadata view may be exposed to any
    authenticated caller — no clinic relationship required. It returns
    only counts; PDL §4 ¶3 satisfied without leaking sources."""
    patient = _patient_or_404(patient_guid)
    if patient is None:
        return _bad("Patient not found", 404)

    rows = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=patient.guid)
        .all()
    )
    active = [r for r in rows if r.is_active()]
    blocked_source_count = len({r.source_scope_id for r in active})
    now_aware = utcnow()
    has_indispensable = any(
        r.lifted_at is not None
        and r.lift_kind == "indispensable_care"
        and r.lift_expires_at is not None
        and _as_aware(r.lift_expires_at) >= now_aware
        for r in rows
    )
    return jsonify({
        "patient_guid": str(patient.guid),
        "blocked_source_count": blocked_source_count,
        "has_active_indispensable_care_lift": has_indispensable,
    }), 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(s):
    from datetime import datetime as _dt
    if not isinstance(s, str):
        return None
    try:
        # Python's fromisoformat accepts e.g. "2026-06-04T10:30:00+00:00"
        return _dt.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
