"""IPS Snapshot model — immutable point-in-time bundle capture."""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


class IpsSnapshot(db.Model):
    __tablename__ = "ips_snapshots"

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    card_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("ips_cards.guid", ondelete="CASCADE"), nullable=False
    )
    bundle_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    composition_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    generated_by_guid: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.guid", ondelete="SET NULL")
    )
    resource_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    card = relationship("IpsCard", back_populates="snapshots")
    generated_by = relationship("User")
    push_jobs = relationship("PushJob", back_populates="snapshot")

    def to_dict(self, include_bundle: bool = False) -> dict:
        result = {
            "guid": str(self.guid),
            "card_guid": str(self.card_guid),
            "composition_date": self.composition_date.isoformat() if self.composition_date else None,
            "mode": self.mode,
            "generated_by_guid": str(self.generated_by_guid) if self.generated_by_guid else None,
            "resource_count": self.resource_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_bundle:
            result["bundle_json"] = self.bundle_json
        return result
