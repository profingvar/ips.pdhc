"""Clinic and UserClinicAssignment models."""

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID


class Clinic(db.Model):
    __tablename__ = "clinics"

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    organisation_guid: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(255), unique=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user_assignments = relationship("UserClinicAssignment", back_populates="clinic", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "organisation_guid": self.organisation_guid,
            "name": self.name,
            "identifier": self.identifier,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserClinicAssignment(db.Model):
    __tablename__ = "user_clinic_assignments"
    __table_args__ = (
        UniqueConstraint("user_guid", "clinic_guid"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    user_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.guid", ondelete="CASCADE"), nullable=False
    )
    clinic_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clinics.guid", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="clinic_assignments")
    clinic = relationship("Clinic", back_populates="user_assignments")
