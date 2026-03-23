"""FHIR CapabilityStatement metadata model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


class CapabilityStatement(db.Model):
    __tablename__ = "capability_statement"

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    resource_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "version": self.version,
            "is_current": self.is_current,
            "resource_json": self.resource_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
