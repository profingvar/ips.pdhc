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
    #: The sso organisation this clinic IS — the **vårdenhet** (care unit).
    organisation_guid: Mapped[str | None] = mapped_column(String(255), unique=True)

    #: The **vårdgivare** (caregiver) above it — the legal entity.
    #:
    #: Added 2026-10-08 for the operator principle: "a guid must have a 1:1
    #: relation to a personnummer, a caregiver and a careunit." ips could not
    #: express that at all before: an assignment recorded ONE unlabelled
    #: organisation, and the caregiver/careunit hierarchy existed only in sso,
    #: so every consumer had to call sso to learn which level it was looking
    #: at. A page cannot say "this is the spärrgräns" without knowing that.
    #:
    #: Synced from sso by `flask sync-care-hierarchy`, not authored here — sso
    #: owns the hierarchy and a second authority would drift from it.
    #:
    #: **When sso says this organisation has no parent (it IS a vårdgivare),
    #: this is set EQUAL to `organisation_guid`.** That is the operator's rule
    #: — "if careunit is not given then the careunit should be set to the
    #: caregiver" — stored rather than recomputed by every reader, so the two
    #: levels are always both answerable and callers cannot each invent their
    #: own fallback.
    care_organisation_guid: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(255), unique=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user_assignments = relationship("UserClinicAssignment", back_populates="clinic", cascade="all, delete-orphan")

    def is_own_caregiver(self) -> bool:
        """True when this clinic is itself the vårdgivare.

        Either sso records no parent for it, or the parent is itself — which is
        how the operator's fallback is stored. Both mean the spärrgräns sits at
        the caregiver level.
        """
        return (not self.care_organisation_guid
                or self.care_organisation_guid == self.organisation_guid)

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "organisation_guid": self.organisation_guid,
            # Both levels, always answerable. `care_unit_guid` is an alias of
            # `organisation_guid` so a consumer never has to know that the
            # unlabelled column meant the unit.
            "care_unit_guid": self.organisation_guid,
            "care_organisation_guid": self.care_organisation_guid,
            "is_own_caregiver": self.is_own_caregiver(),
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
