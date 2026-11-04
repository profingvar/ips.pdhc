"""Generic FHIR Resource storage model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


class FhirResource(db.Model):
    __tablename__ = "fhir_resources"
    __table_args__ = (
        Index("ix_fhir_resources_type", "resource_type"),
        Index("ix_fhir_resources_patient", "patient_guid"),
        Index("ix_fhir_resources_type_patient", "resource_type", "patient_guid"),
        Index("ix_fhir_resources_last_updated", "last_updated"),
        # GIN index for JSONB containment queries — created via raw SQL in migration
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resource_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    patient_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    status: Mapped[str | None] = mapped_column(String(32), default="active")
    #: Declared BEFORE last_updated on purpose (#928). Both carried
    #: `default=utcnow` and SQLAlchemy calls the callable once PER COLUMN, so
    #: the two values differed by microseconds — and in the old declaration
    #: order `last_updated` was read FIRST, which made it EARLIER than
    #: `created_at` on 2355 of 4780 production rows. A modification can only
    #: ever be later, so that was the proof the difference was clock noise and
    #: not an update. The listener below removes it; this order is the
    #: belt-and-braces if the listener is ever lost.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    #: #928: `onupdate` is what makes this column mean its name. Without it
    #: `default=` applied on INSERT and nothing ever touched it again, so this
    #: was a CREATION timestamp wearing a modification timestamp's name — while
    #: carrying an index (`ix_fhir_resources_last_updated`) that invites
    #: exactly the "what changed recently" query it could not answer. Two live
    #: queries take that invitation: `fhir_service.search_resources` and
    #: `admin.patient_detail` both `order_by(last_updated.desc())`.
    #:
    #: It does NOT repair history. Every row written before this keeps a value
    #: meaning "created", and measured 2026-11-04 that is all 4780 of them.
    #:
    #: It is also the honest signal for the two IN-PLACE writers
    #: (`app/__init__.py:257`, `euips_header_backfill.py:178`), which assign
    #: `resource_json` directly and so bypass `update_resource`'s append-only
    #: versioning. Bumping `version_id` in place would be worse than silence:
    #: in this model v2 means v1 survives as `status='superseded'`, and a row
    #: claiming v2 with no v1 would assert a history that does not exist.
    #: A time is a claim this schema can keep. Whether a backfill should create
    #: a version instead of mutating in place is #934 — it has a row-count
    #: consequence and was deliberately not decided here.
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   default=utcnow,
                                                   onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "version_id": self.version_id,
            "resource_json": self.resource_json,
            "patient_guid": str(self.patient_guid) if self.patient_guid else None,
            "status": self.status,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@db.event.listens_for(FhirResource, "before_insert")
def _one_clock_read_per_row(mapper, connection, target):
    """#928: `created_at` and `last_updated` share ONE clock read at insert.

    `default=utcnow` is evaluated once per COLUMN, so a fresh row got two
    timestamps microseconds apart. Measured in production 2026-11-04: 2355 of
    4780 rows had `last_updated != created_at`, every difference under 1 ms
    (max 14 µs), and every one with `last_updated` EARLIER.

    That is worse than cosmetic. Half the table looked modified to anyone
    reading `last_updated != created_at` as evidence of a change, which is the
    kind of reasoning #927's investigation rested on. Sharing one value makes
    "these differ" mean something again: after this, a difference IS a
    modification.
    """
    now = target.created_at or utcnow()
    target.created_at = now
    target.last_updated = now
