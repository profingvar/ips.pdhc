"""PatientBlock — spärr Phase 1 (ticket #197).

Implements the data layer for the patient's right under PDL Ch 4 § 4
to block reading of their data from a specific source (clinic in v1;
caregiver-level scope is IPS Renov 8 / #204).

A block is the *source-scope* assertion: "data authored at scope S is
hidden from readers outside S, for patient P". The block lives at
ips.pdhc; consumers (dashboard, gateway, cdr_6) fetch the list and
filter their reads. See analysis/sparr_implementation_plan.md.

Lifts (PDL Ch 4 § 5) are recorded inline on the same row by setting
``lifted_at`` and friends; ``lift_kind`` distinguishes the two paths:

- ``consent`` — patient consents on the spot; permanent until
  re-imposed.
- ``indispensable_care`` — clinician overrides for indispensable care;
  must carry a *mechanical filter* (``lift_concept_guids``,
  ``lift_from_date``, ``lift_until_date``) — legal-confirmed 2026-06-04
  as REQUIRED, not advisory. The lift auto-expires after
  ``lift_expires_at`` (default 24 h).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


def _as_aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes from ``DateTime(timezone=True)``
    columns; treat naive values as UTC so comparisons don't blow up in
    the test path."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Enum values kept as plain strings (portable across PG/SQLite via
# our base.py shim); validated at the API layer.
BLOCK_SCOPE_TYPES = ("clinic", "caregiver")
BLOCK_LIFT_KINDS = ("consent", "indispensable_care")


class PatientBlock(db.Model):
    __tablename__ = "patient_blocks"
    __table_args__ = (
        Index("ix_patient_blocks_patient", "patient_guid"),
        Index("ix_patient_blocks_source_scope",
              "source_scope_type", "source_scope_id"),
        # Partial unique would be ideal — only one ACTIVE block per
        # (patient, scope) — but Index(..., postgresql_where=...) breaks
        # the SQLite test path. The API enforces uniqueness via a
        # pre-insert check (409 on duplicate active); the DB-side
        # guarantee can be tightened with a partial unique index in a
        # future migration once we leave SQLite tests.
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )

    # The patient who imposed the block — FK to PatientIndex.guid.
    patient_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("patient_index.guid", ondelete="CASCADE"),
        nullable=False,
    )

    # The source scope whose data is blocked. v1: clinic only.
    source_scope_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="clinic"
    )
    source_scope_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    # Lifecycle — created and (maybe later) lifted.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by_user_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    created_reason: Mapped[str | None] = mapped_column(Text)

    # Optional time bound on the block itself. NULL = open-ended until
    # explicitly lifted. When set and ``expires_at < now`` the IPS
    # background sweep (#202) flips the row to ``lifted`` with
    # ``lifted_reason='expired'`` and fires a block.expired webhook.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifted_by_user_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    lifted_reason: Mapped[str | None] = mapped_column(Text)
    lift_kind: Mapped[str | None] = mapped_column(String(32))

    # When lift_kind = 'indispensable_care', the block auto-re-asserts
    # after this time. NULL for consent lifts (permanent) and for
    # un-lifted blocks. Background re-imposition is IPS Renov 6 /
    # ticket #202 (out of scope here).
    lift_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Mechanical filter on indispensable-care lifts (legal 2026-06-04 —
    # REQUIRED, not advisory). The lift exposes ONLY the named concept
    # GUIDs within the named date range. NULL on consent lifts and on
    # un-lifted blocks. The consumer side enforces:
    #   row.concept_guid IN lift_concept_guids
    #   AND (lift_from_date IS NULL OR row.effective_at >= lift_from_date)
    #   AND (lift_until_date IS NULL OR row.effective_at <= lift_until_date)
    lift_concept_guids: Mapped[list | None] = mapped_column(JSONB)
    lift_from_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lift_until_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    patient = relationship("PatientIndex")

    def is_active(self, at: datetime | None = None) -> bool:
        """True when the block is currently blocking reads.

        Returns False when:
          - the row has been lifted AND the lift is permanent
            (consent), OR
          - the row has been lifted via indispensable_care and the
            lift has not yet auto-re-asserted, OR
          - the block itself has an ``expires_at`` that has passed
            (treated as expired-by-time; #202).

        Indispensable-care lifts whose ``lift_expires_at`` has passed
        are treated as re-imposed (the IPS sweep job in #202 will
        persist this; ``is_active`` reflects the truth even before the
        sweep runs).
        """
        now = at or utcnow()
        # Time-bound expiry on the block itself wins over lift state —
        # an expired block is no longer blocking, period.
        if self.expires_at is not None and \
                _as_aware(self.expires_at) <= _as_aware(now):
            return False
        if self.lifted_at is None:
            return True
        if self.lift_kind == "consent":
            return False
        # indispensable_care: re-imposed once the lift expires
        if self.lift_expires_at is None:
            return False
        return _as_aware(self.lift_expires_at) < _as_aware(now)

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "patient_guid": str(self.patient_guid),
            "source_scope_type": self.source_scope_type,
            "source_scope_id": str(self.source_scope_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by_user_guid": (
                str(self.created_by_user_guid)
                if self.created_by_user_guid else None
            ),
            "created_reason": self.created_reason,
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "lifted_at": self.lifted_at.isoformat() if self.lifted_at else None,
            "lifted_by_user_guid": (
                str(self.lifted_by_user_guid)
                if self.lifted_by_user_guid else None
            ),
            "lifted_reason": self.lifted_reason,
            "lift_kind": self.lift_kind,
            "lift_expires_at": (
                self.lift_expires_at.isoformat()
                if self.lift_expires_at else None
            ),
            "lift_concept_guids": self.lift_concept_guids,
            "lift_from_date": (
                self.lift_from_date.isoformat()
                if self.lift_from_date else None
            ),
            "lift_until_date": (
                self.lift_until_date.isoformat()
                if self.lift_until_date else None
            ),
            "is_active": self.is_active(),
        }
