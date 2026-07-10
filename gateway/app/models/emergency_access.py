"""EmergencyAccess — nödöppning grants (D3 #406, PDL 6 kap 5 §).

A time-bound, attested grant that lets ONE reading care unit read a
patient's data past spärr and absent cohesive-care consent, in an acute
situation (fara för patientens liv eller hälsa). Distinct from the
indispensable-care BLOCK LIFT (#244, PDL 4 kap 5 §): a lift alters one
block row; a nödöppning grant overrides the whole zone composition for
the reading unit while it lives, and is evaluated by
``care_access_policy.evaluate_care_access`` — the block rows themselves
are untouched.

INSERT-only: a grant is never edited or deleted; it simply expires.
Every grant is audited with access_basis=emergency and surfaces to the
patient via the portal banner (patient_portal) and the audit trail.
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy import String, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import db, new_uuid, utcnow, GUID


# Legal default mirrors the indispensable-lift window (legal 2026-06-04:
# 24 h explicitly allowed); override per-grant via expires_in.
DEFAULT_EMERGENCY_ACCESS_SECONDS = 24 * 60 * 60


def _as_aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class EmergencyAccess(db.Model):
    __tablename__ = "emergency_access"
    __table_args__ = (
        Index("ix_emergency_access_patient", "patient_guid"),
        Index("ix_emergency_access_reader_unit", "reader_care_unit_guid"),
    )

    guid: Mapped[str] = mapped_column(GUID(), primary_key=True,
                                      default=new_uuid)
    patient_guid: Mapped[str] = mapped_column(
        GUID(), ForeignKey("patient_index.guid"), nullable=False)

    # The reading context the grant applies to (the unit that invoked
    # nödöppning — NOT the authoring side).
    reader_care_unit_guid: Mapped[str] = mapped_column(GUID(), nullable=False)
    reader_care_organisation_guid: Mapped[str] = mapped_column(
        GUID(), nullable=True)

    # Attestation (legal): who, why, that they attested, and when.
    actor_user_guid: Mapped[str] = mapped_column(GUID(), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)

    # Set when the patient-facing notification surfaced (portal banner
    # render or future push channel) — the legal duty is to notify, the
    # timestamp proves it happened.
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True)

    session_id: Mapped[str] = mapped_column(String(128), nullable=True)

    def is_active(self, now=None) -> bool:
        now = now or datetime.now(timezone.utc)
        return _as_aware(self.expires_at) > now

    @staticmethod
    def default_expiry(now=None):
        now = now or datetime.now(timezone.utc)
        return now + timedelta(seconds=DEFAULT_EMERGENCY_ACCESS_SECONDS)

    def to_dict(self) -> dict:
        def iso(dt):
            return _as_aware(dt).isoformat() if dt else None
        return {
            "guid": str(self.guid),
            "patient_guid": str(self.patient_guid),
            "reader_care_unit_guid": str(self.reader_care_unit_guid),
            "reader_care_organisation_guid": (
                str(self.reader_care_organisation_guid)
                if self.reader_care_organisation_guid else None),
            "actor_user_guid": (str(self.actor_user_guid)
                                if self.actor_user_guid else None),
            "actor_label": self.actor_label,
            "reason": self.reason,
            "attested_at": iso(self.attested_at),
            "created_at": iso(self.created_at),
            "expires_at": iso(self.expires_at),
            "notified_at": iso(self.notified_at),
            "is_active": self.is_active(),
        }
