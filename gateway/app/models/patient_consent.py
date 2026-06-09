"""PatientConsent — IPS Renov 2 (ticket #198).

Peer model to PatientBlock. Records cohesive-care consent (Lag
2022:913 § 5): a patient affirmatively allowing another caregiver
(``grantee_caregiver_guid``) to read their data, optionally narrowed
to a list of concepts.

A consent is the *grant* side of cross-caregiver sharing: "caregiver
G may read patient P's data, optionally only concepts C[]". The
consent lives at ips.pdhc; consumers (request.pdhc dispatch,
cdr_6 cross-caregiver reads) fetch it and gate their behaviour. The
consumer enforcement is intentionally out of scope here — this
ticket lands the durable store + REST surface + audit hooks.

Per legal 2026-06-04 the recording shape is a simple note (no formal
witness chain required); ``granted_via`` captures the channel.

Lifecycle is INSERT-only — revocation flips ``revoked_at`` and
friends on the same row. ``is_active`` returns True iff:
  - ``revoked_at`` is NULL, AND
  - ``expires_at`` is NULL or still in the future.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


def _as_aware(dt: datetime) -> datetime:
    """SQLite test path returns naive datetimes from timezone columns;
    treat naive as UTC so ``is_active`` comparisons don't blow up."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# How the consent was captured. Validated at the API layer; kept as
# plain strings (portable across PG/SQLite). 'contract' is the
# auto-emit channel from contract.pdhc when a patient is in the
# contract's signer[] (#231).
CONSENT_GRANTED_VIA = (
    "portal", "in_person", "paper", "phone", "contract", "other",
)


class PatientConsent(db.Model):
    __tablename__ = "patient_consents"
    __table_args__ = (
        Index("ix_patient_consents_patient", "patient_guid"),
        Index(
            "ix_patient_consents_grantee",
            "grantee_caregiver_guid",
        ),
        # A patient may have multiple consents to the same caregiver
        # over time (revoke + re-grant); uniqueness is "only one
        # ACTIVE consent per (patient, grantee)" and is enforced at
        # the API layer (parity with PatientBlock).
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )

    # The patient who granted the consent — FK to PatientIndex.guid.
    patient_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("patient_index.guid", ondelete="CASCADE"),
        nullable=False,
    )

    # The caregiver allowed to read. References an organisation guid at
    # the vårdgivare level (the SSO Phase 1 caregiver roll-up, #188);
    # not FK'd because organisations live in sso.pdhc.
    grantee_caregiver_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False,
    )

    # Optional link back to the contract that triggered the consent
    # (the contract.pdhc auto-emit path, #231). Stored as a guid string
    # because contracts live in contract.pdhc.
    contract_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())

    # Lifecycle.
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    granted_by_user_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    granted_via: Mapped[str] = mapped_column(
        String(32), nullable=False, default="portal",
    )
    granted_note: Mapped[str | None] = mapped_column(Text)

    # Optional time bound. NULL = open-ended until revoked.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    revoked_by_user_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    revoked_reason: Mapped[str | None] = mapped_column(Text)

    # Optional concept-level narrowing. NULL = whole-caregiver consent.
    # When set, only data carrying one of these concept_guids falls
    # under the consent.
    consented_concept_guids: Mapped[list | None] = mapped_column(JSONB)

    patient = relationship("PatientIndex")

    def is_active(self, at: datetime | None = None) -> bool:
        """True when the consent currently authorises reads."""
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        now = at or utcnow()
        return _as_aware(self.expires_at) > _as_aware(now)

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "patient_guid": str(self.patient_guid),
            "grantee_caregiver_guid": str(self.grantee_caregiver_guid),
            "contract_guid": (
                str(self.contract_guid) if self.contract_guid else None
            ),
            "granted_at": (
                self.granted_at.isoformat() if self.granted_at else None
            ),
            "granted_by_user_guid": (
                str(self.granted_by_user_guid)
                if self.granted_by_user_guid else None
            ),
            "granted_via": self.granted_via,
            "granted_note": self.granted_note,
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "revoked_at": (
                self.revoked_at.isoformat() if self.revoked_at else None
            ),
            "revoked_by_user_guid": (
                str(self.revoked_by_user_guid)
                if self.revoked_by_user_guid else None
            ),
            "revoked_reason": self.revoked_reason,
            "consented_concept_guids": self.consented_concept_guids,
            "is_active": self.is_active(),
        }
