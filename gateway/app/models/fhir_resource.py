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
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

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
