"""Push Job model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID


class PushJob(db.Model):
    __tablename__ = "push_jobs"

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    snapshot_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("ips_snapshots.guid", ondelete="CASCADE"), nullable=False
    )
    destination_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("push_destinations.guid", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    response_code: Mapped[int | None] = mapped_column(Integer)
    initiated_by_guid: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.guid", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    snapshot = relationship("IpsSnapshot", back_populates="push_jobs")
    destination = relationship("PushDestination")
    initiated_by = relationship("User")

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "snapshot_guid": str(self.snapshot_guid),
            "destination_guid": str(self.destination_guid),
            "status": self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "response_code": self.response_code,
            "initiated_by_guid": str(self.initiated_by_guid) if self.initiated_by_guid else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
