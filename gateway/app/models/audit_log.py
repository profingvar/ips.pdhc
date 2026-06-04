"""Audit Log model — append-only."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor", "actor_guid"),
        Index("ix_audit_log_patient", "patient_guid"),
        Index("ix_audit_log_event_type", "event_type"),
        Index("ix_audit_log_created", "created_at"),
        Index("ix_audit_log_session_id", "session_id"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )
    actor_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    actor_type: Mapped[str | None] = mapped_column(String(32))
    actor_label: Mapped[str | None] = mapped_column(String(255))
    patient_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    request_path: Mapped[str | None] = mapped_column(String(2048))
    request_method: Mapped[str | None] = mapped_column(String(10))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    # Ticket #203: SSO session_id (sid claim, see #191 + sso.pdhc
    # integration-guide.md "Operator Session Correlation"). Nullable —
    # legacy callers (API-key services without an X-Operator-Session-Id
    # header, AUTH_DISABLED dev blob without the claim) leave it NULL.
    # Indexed because the canonical PDL kontroller query is
    # "all rows for session S".
    session_id: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "actor_guid": str(self.actor_guid) if self.actor_guid else None,
            "actor_type": self.actor_type,
            "actor_label": self.actor_label,
            "patient_guid": str(self.patient_guid) if self.patient_guid else None,
            "event_type": self.event_type,
            "resource_type": self.resource_type,
            "resource_guid": str(self.resource_guid) if self.resource_guid else None,
            "request_path": self.request_path,
            "request_method": self.request_method,
            "ip_address": self.ip_address,
            "session_id": self.session_id,
            "detail": self.detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
