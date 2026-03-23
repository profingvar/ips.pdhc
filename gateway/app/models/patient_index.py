"""Patient index and patient-clinic assignment models."""

import uuid
from datetime import datetime, date

from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID


class PatientIndex(db.Model):
    __tablename__ = "patient_index"
    __table_args__ = (
        Index("ix_patient_index_identifier", "identifier_system", "identifier_value"),
        Index("ix_patient_index_name", "family_name", "given_name"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    fhir_resource_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fhir_resources.guid", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    identifier_system: Mapped[str | None] = mapped_column(String(255))
    identifier_value: Mapped[str | None] = mapped_column(String(255))
    family_name: Mapped[str | None] = mapped_column(String(255))
    given_name: Mapped[str | None] = mapped_column(String(255))
    birth_date: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    fhir_resource = relationship("FhirResource")
    clinic_assignments = relationship("PatientClinicAssignment", back_populates="patient", cascade="all, delete-orphan")
    ips_cards = relationship("IpsCard", back_populates="patient")

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "resource_id": self.resource_id,
            "identifier_system": self.identifier_system,
            "identifier_value": self.identifier_value,
            "family_name": self.family_name,
            "given_name": self.given_name,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "gender": self.gender,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PatientClinicAssignment(db.Model):
    __tablename__ = "patient_clinic_assignments"
    __table_args__ = (
        UniqueConstraint("patient_guid", "clinic_guid"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    patient_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("patient_index.guid", ondelete="CASCADE"), nullable=False
    )
    clinic_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clinics.guid", ondelete="CASCADE"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient = relationship("PatientIndex", back_populates="clinic_assignments")
    clinic = relationship("Clinic")
