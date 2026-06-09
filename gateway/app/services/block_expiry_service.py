"""Background sweep for PatientBlock expiry — IPS Renov 6 (#202).

Two passes that run together; both are pure DB transitions that emit
an AuditLog row (via ``log_event``) and dispatch a block-state webhook
(via ``safe_dispatch``):

  1. expire_blocks(): rows where ``expires_at < now`` AND not yet
     lifted. Sets ``lifted_at = expires_at``,
     ``lifted_reason = 'expired'``, ``lift_kind = None``. Emits
     ``block.expired``.

  2. re_impose_indispensable_lifts(): rows where
     ``lifted_at IS NOT NULL`` AND
     ``lift_kind = 'indispensable_care'`` AND
     ``lift_expires_at < now``. Clears ``lifted_at`` /
     ``lifted_by_user_guid`` / ``lifted_reason`` / ``lift_kind`` /
     ``lift_expires_at`` / ``lift_concept_guids`` /
     ``lift_from_date`` / ``lift_until_date`` so the row is back to a
     fresh active block. Emits ``block.re_imposed``.

Run via ``flask sweep-blocks`` from cron, or any external scheduler.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.models.base import db, utcnow
from app.models.patient_block import PatientBlock, _as_aware
from app.services.audit_service import log_event
from app.services.block_webhook import safe_dispatch


log = logging.getLogger(__name__)


def _now(at: Optional[datetime]) -> datetime:
    return at or utcnow()


def expire_blocks(at: Optional[datetime] = None) -> dict:
    """Flip every block whose ``expires_at`` has passed to
    ``lifted/'expired'``.

    Returns ``{"expired": N, "block_guids": [...]}``.
    """
    now = _now(at)
    rows = (
        db.session.query(PatientBlock)
        .filter(PatientBlock.expires_at.isnot(None))
        .filter(PatientBlock.lifted_at.is_(None))
        .all()
    )
    summary = {"expired": 0, "block_guids": []}
    for row in rows:
        if _as_aware(row.expires_at) > _as_aware(now):
            continue
        # Use the configured expiry time as the lift timestamp so the
        # audit chain reflects when the block became inert (not when
        # the sweep noticed).
        row.lifted_at = row.expires_at
        row.lifted_reason = "expired"
        row.lifted_by_user_guid = None
        row.lift_kind = None  # not a consent / indispensable_care lift
        db.session.flush()
        log_event(
            event_type="block.expired",
            patient_guid=row.patient_guid,
            resource_type="PatientBlock",
            resource_guid=row.guid,
            detail={
                "expires_at": (
                    row.expires_at.isoformat() if row.expires_at else None
                ),
                "source_scope_type": row.source_scope_type,
                "source_scope_id": str(row.source_scope_id),
            },
        )
        safe_dispatch("block.expired", row)
        summary["expired"] += 1
        summary["block_guids"].append(str(row.guid))
    if summary["expired"]:
        db.session.commit()
    return summary


def re_impose_indispensable_lifts(
    at: Optional[datetime] = None,
) -> dict:
    """Re-impose every block whose indispensable_care lift has
    timed out.

    Returns ``{"re_imposed": N, "block_guids": [...]}``.
    """
    now = _now(at)
    rows = (
        db.session.query(PatientBlock)
        .filter(PatientBlock.lifted_at.isnot(None))
        .filter(PatientBlock.lift_kind == "indispensable_care")
        .filter(PatientBlock.lift_expires_at.isnot(None))
        .all()
    )
    summary = {"re_imposed": 0, "block_guids": []}
    for row in rows:
        if _as_aware(row.lift_expires_at) > _as_aware(now):
            continue
        # Clear the entire lift record — the block is fresh-active
        # again. The history is in the AuditLog (block.lifted +
        # block.re_imposed pairs).
        previous_lift_expires_at = row.lift_expires_at
        row.lifted_at = None
        row.lifted_by_user_guid = None
        row.lifted_reason = None
        row.lift_kind = None
        row.lift_expires_at = None
        row.lift_concept_guids = None
        row.lift_from_date = None
        row.lift_until_date = None
        db.session.flush()
        log_event(
            event_type="block.re_imposed",
            patient_guid=row.patient_guid,
            resource_type="PatientBlock",
            resource_guid=row.guid,
            detail={
                "previous_lift_expires_at": (
                    previous_lift_expires_at.isoformat()
                    if previous_lift_expires_at else None
                ),
                "source_scope_type": row.source_scope_type,
                "source_scope_id": str(row.source_scope_id),
            },
        )
        safe_dispatch("block.re_imposed", row)
        summary["re_imposed"] += 1
        summary["block_guids"].append(str(row.guid))
    if summary["re_imposed"]:
        db.session.commit()
    return summary


def sweep(at: Optional[datetime] = None) -> dict:
    """One-shot: expire then re-impose. Used by the CLI."""
    now = _now(at)
    return {
        "expired": expire_blocks(at=now),
        "re_imposed": re_impose_indispensable_lifts(at=now),
    }
