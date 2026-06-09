"""Admin emergency / indispensable-care block-lift route — IPS Renov 5 (#201).

PDL Ch 4 § 5 carve-out: a clinician with elevated role may lift an
active block to access blocked data for indispensable care, *only*
with a written justification, *only* for an explicit concept set,
and *only* for 24 hours by default (the lift auto-re-asserts via the
#202 background sweep at ``lift_expires_at``).

Distinct from the patient-scoped lift route in ``blocks_routes`` —
that route handles ``lift_kind='consent'`` (the patient ok'ing the
read) AND ``lift_kind='indispensable_care'``, but auth there only
needs ``PatientClinicAssignment`` to the patient. This route is the
narrower emergency path: no patient relationship is required (the
clinician is treating *this patient now*, often without prior
assignment); the safeguard is the role gate.

  POST  /api/v1/admin/blocks/<block_guid>/lift
  Body: {
    reason:        str (required, non-empty)
    concept_guids: [str] (required, non-empty — mechanical filter,
                          legal 2026-06-04 REQUIRED)
    expires_in:    int  (seconds; default 24h)
    from_date:     ISO-8601 (optional concept date narrowing)
    until_date:    ISO-8601 (optional concept date narrowing)
  }

  Auth: SU admin always passes. Otherwise role must be in
        ``INDISPENSABLE_LIFT_ROLES``. Configurable via the
        ``IPS_INDISPENSABLE_LIFT_ROLES`` env (comma-separated).

  Audit shape (block.lifted event with detail.mechanism="indispensable_care"
  + detail.actor_user_guid + detail.reason verbatim).

  Webhook: block.lifted fires post-commit via ``safe_dispatch`` —
  same convention as ``blocks_routes`` so subscriber caches drop
  the row immediately.
"""
from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from app.models.base import db, utcnow
from app.models.patient_block import PatientBlock
from app.services.audit_service import log_event
from app.services.auth_service import require_auth
from app.services.block_webhook import safe_dispatch as _emit_block_webhook


bp = Blueprint("admin_blocks_api", __name__, url_prefix="/api/v1/admin/blocks")


# Same default the patient-scoped lift route uses (legal 2026-06-04:
# 24h is explicitly allowed; consumers can override per-lift via
# expires_in).
DEFAULT_INDISPENSABLE_LIFT_SECONDS = 24 * 60 * 60


def _allowed_roles() -> set:
    """Roles permitted on the admin indispensable-care lift path.

    Defaults to {'physician', 'admin'}. Override via
    ``IPS_INDISPENSABLE_LIFT_ROLES`` env (comma-separated). SU admins
    (``is_superuser=True``) always pass regardless of this set."""
    raw = (
        current_app.config.get("IPS_INDISPENSABLE_LIFT_ROLES")
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


def _parse_iso(s):
    from datetime import datetime as _dt
    if not isinstance(s, str):
        return None
    try:
        return _dt.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@bp.route("/<block_guid>/lift", methods=["POST"])
@require_auth
def admin_indispensable_lift(block_guid):
    """Emergency lift of an active block for indispensable care."""
    if not _is_physician_or_su(getattr(g, "current_user", None)):
        return _bad(
            "Not authorised: indispensable-care lift requires "
            "SU admin or physician role",
            403,
        )

    try:
        block_guid_obj = UUID(str(block_guid))
    except (ValueError, TypeError):
        return _bad("Invalid block_guid", 404)

    block = (
        db.session.query(PatientBlock)
        .filter_by(guid=block_guid_obj)
        .first()
    )
    if block is None:
        return _bad("Block not found", 404)
    if not block.is_active():
        # 409 — semantically the resource is in the wrong state, not
        # missing. Mirrors blocks_routes which returns 404 here, but
        # 409 is the more honest answer.
        return _bad("Block is already lifted", 409)

    payload = request.get_json(silent=True) or {}

    reason = (payload.get("reason") or "").strip()
    if not reason:
        return _bad(
            "reason is required for indispensable_care lift "
            "(PDL Ch 4 §5 mandates written justification)",
            400,
        )

    concept_guids_raw = payload.get("concept_guids") or []
    if not isinstance(concept_guids_raw, list) or not concept_guids_raw:
        return _bad(
            "concept_guids is required for indispensable_care lift "
            "(legal 2026-06-04: mechanical filter required)",
            400,
        )
    try:
        concept_guids = [str(UUID(str(c))) for c in concept_guids_raw]
    except (ValueError, TypeError):
        return _bad("concept_guids must all be valid UUIDs", 400)

    try:
        expires_in = int(
            payload.get("expires_in")
            or DEFAULT_INDISPENSABLE_LIFT_SECONDS
        )
    except (TypeError, ValueError):
        return _bad("expires_in must be an integer number of seconds", 400)
    if expires_in <= 0:
        return _bad("expires_in must be a positive number of seconds", 400)

    from_date = None
    until_date = None
    from_date_raw = payload.get("from_date")
    if from_date_raw:
        from_date = _parse_iso(from_date_raw)
        if from_date is None:
            return _bad("from_date must be ISO 8601", 400)
    until_date_raw = payload.get("until_date")
    if until_date_raw:
        until_date = _parse_iso(until_date_raw)
        if until_date is None:
            return _bad("until_date must be ISO 8601", 400)

    now = utcnow()
    block.lifted_at = now
    block.lifted_by_user_guid = getattr(g.current_user, "guid", None)
    block.lifted_reason = reason
    block.lift_kind = "indispensable_care"
    block.lift_concept_guids = concept_guids
    block.lift_expires_at = now + timedelta(seconds=expires_in)
    block.lift_from_date = from_date
    block.lift_until_date = until_date

    db.session.flush()

    actor_guid = getattr(g.current_user, "guid", None)
    log_event(
        event_type="block.lifted",
        patient_guid=block.patient_guid,
        resource_type="PatientBlock",
        resource_guid=block.guid,
        detail={
            "lift_kind": "indispensable_care",
            "mechanism": "indispensable_care",
            "actor_user_guid": (
                str(actor_guid) if actor_guid else None
            ),
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
            "admin_route": True,
        },
    )
    db.session.commit()

    # Ticket #202: invalidation hint for consumer caches.
    _emit_block_webhook("block.lifted", block)

    return jsonify(block.to_dict()), 200
