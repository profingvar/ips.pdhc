"""IPS Card model."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID


class IpsCard(db.Model):
    __tablename__ = "ips_cards"

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    patient_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("patient_index.guid", ondelete="CASCADE"), nullable=False
    )
    clinic_guid: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("clinics.guid", ondelete="SET NULL")
    )
    created_by_guid: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.guid", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="full")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    patient = relationship("PatientIndex", back_populates="ips_cards")
    clinic = relationship("Clinic")
    created_by = relationship("User")
    snapshots = relationship("IpsSnapshot", back_populates="card", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "patient_guid": str(self.patient_guid),
            "clinic_guid": str(self.clinic_guid) if self.clinic_guid else None,
            "created_by_guid": str(self.created_by_guid) if self.created_by_guid else None,
            "title": self.title,
            "status": self.status,
            "mode": self.mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
