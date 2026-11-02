"""PatientProxyGrant — a patient-granted next-of-kin privilege (EPS C3, #889).

Peer model to :class:`PatientConsent`, and deliberately a SEPARATE table
rather than a row shape inside it. #889 requires this in those words, for
the same reason advance directives were kept out of ``patient_consents``:
a cohesive-care consent authorises a CAREGIVER to read, under
Lag (2022:913) § 5. This authorises a PRIVATE INDIVIDUAL to act for the
patient. Folding the second into the first would put two different legal
bases in one table and make "who may read?" unanswerable without knowing
which kind of row you were looking at.

The identity side lives in sso.pdhc (#890, EPS C3a): a ``users`` row with
``user_type='relative'`` plus a ``relatives`` profile. **The grant itself
lives here**, which is a deliberate correction to #890's own §5 sketch:

  - #889 requires the grant beside ``patient_consents``, an ips table.
  - patient self-determination over blocks and consents already lives in
    ips, and this is the same kind of act.
  - sso is the bottom of the dependency stack. Had the grant lived there,
    either sso would have to ask ips (a downstream dependency) or the
    patient's own grants would be administered in a service that does not
    own any of their other self-determination rows.

So the SSO blob carries only identity — ``user_type='relative'`` and the
relative's own guid. It does NOT carry a ``patient_guid``: sso does not
know which patients a relative may act for. ips resolves that here.

That keeps #890's load-bearing property exactly as stated, only relocated:

    the grant is resolved from the DATABASE on every request and is never
    baked into a token

so a grant revoked at 10:00:00 is gone from the request at 10:00:01, with
no logout, no token revocation and no service-side invalidation.

LIFECYCLE is INSERT-only, as with PatientConsent: revocation flips
``revoked_at`` on the same row, so the history of who could act for whom
is never destroyed. ``is_active`` is True iff the row is unrevoked AND
*now* falls inside ``[valid_from, valid_to)``.

VALIDITY INTERVAL from the start (#889, EPS C1). Unlike PatientConsent,
which carries only ``expires_at``, a proxy grant has both ends. A
relative may be given access from a future date — "while I am in
hospital next month" — and ``expires_at`` alone cannot say that.

WHO MAY DO WHAT, ratified by the operator in EPS A3 (#879):

    both parties may REDUCE access; only the patient may INCREASE it

So the patient may create, narrow or revoke; the relative may revoke
their own grant and nothing else. ``revoked_by_user_guid`` therefore
holds either party, and ``revoked_by_role`` records which — an audit of
"who ended this" that does not require joining back to sso.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID


def _as_aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes from timezone columns; treat naive
    as UTC so interval comparisons don't blow up. Same helper, same
    reason, as PatientConsent — and the reason is sharper here, because a
    naive/aware mix does not merely break an assertion, it silently
    corrupts the comparison (the lesson from EPS C2's as_at tests)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# What the grant lets the relative do. Only READ_AS_PATIENT is enforced
# today; SEPARATE_CHANNEL is A3's second clause (the relative may receive
# and give separate information through a coming app) and is accepted so
# the column does not have to change when that app arrives.
SCOPE_READ_AS_PATIENT = "read_as_patient"
SCOPE_SEPARATE_CHANNEL = "separate_channel"
PROXY_SCOPES = (SCOPE_READ_AS_PATIENT, SCOPE_SEPARATE_CHANNEL)

# How the grant was captured — mirrors CONSENT_GRANTED_VIA so the two
# tables can be audited with one vocabulary.
PROXY_GRANTED_VIA = ("portal", "in_person", "paper", "phone", "other")

# Which party ended it. Both may (A3); only the patient may create.
ENDED_BY_PATIENT = "patient"
ENDED_BY_PROXY = "proxy"


class PatientProxyGrant(db.Model):
    __tablename__ = "patient_proxy_grants"
    __table_args__ = (
        Index("ix_patient_proxy_grants_patient", "patient_guid"),
        Index("ix_patient_proxy_grants_proxy", "proxy_user_guid"),
        # Uniqueness is "only one ACTIVE grant per (patient, proxy)" and
        # is enforced at the API layer, exactly as PatientBlock and
        # PatientConsent do it. A database-level UNIQUE over the pair
        # would make revocation TERMINAL for that pair for ever, which
        # is #891's lesson: ending a relationship is history, not a
        # terminal state, and the same two people must be able to grant,
        # revoke and grant again.
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid
    )

    # The patient who granted it — FK to PatientIndex.guid.
    patient_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("patient_index.guid", ondelete="CASCADE"),
        nullable=False,
    )

    # The relative's sso.pdhc ``users.guid`` (#890). Not FK'd because
    # users live in sso — the same convention as
    # PatientConsent.grantee_caregiver_guid.
    #
    # It is the USER guid and not the ``relatives`` profile guid on
    # purpose: the user row is what authenticates, carries the
    # revocation epoch and can be suspended, so it is the identity whose
    # revocation must propagate here.
    proxy_user_guid: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    # A label the PATIENT chose, e.g. "min dotter Anna". Not identity
    # data and never used for matching — it exists so the patient's own
    # grant list is readable to them.
    proxy_label: Mapped[str | None] = mapped_column(String(255))

    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SCOPE_READ_AS_PATIENT,
    )

    # --- validity interval (#889 / EPS C1). BOTH ends, from the start.
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    # NULL = open-ended until revoked.
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    # --- record time, separate from validity time (EPS C2's bitemporal
    # lesson). When we learned of the grant is not when it became true.
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    granted_by_user_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    granted_via: Mapped[str] = mapped_column(
        String(32), nullable=False, default="portal",
    )
    granted_note: Mapped[str | None] = mapped_column(Text)

    # --- revocation. Either party (A3).
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    revoked_by_user_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    revoked_by_role: Mapped[str | None] = mapped_column(String(16))
    revoked_reason: Mapped[str | None] = mapped_column(Text)

    patient = relationship("PatientIndex")

    # ------------------------------------------------------------------
    def is_active(self, at: datetime | None = None) -> bool:
        """True when this grant currently authorises the relative to act.

        Unrevoked AND *now* inside ``[valid_from, valid_to)``. A grant
        whose ``valid_from`` is in the future is NOT active yet — which
        is the whole point of carrying both ends.
        """
        if self.revoked_at is not None:
            return False
        now = _as_aware(at or utcnow())
        if _as_aware(self.valid_from) > now:
            return False
        if self.valid_to is not None and _as_aware(self.valid_to) <= now:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "guid": str(self.guid),
            "patient_guid": str(self.patient_guid),
            "proxy_user_guid": str(self.proxy_user_guid),
            "proxy_label": self.proxy_label,
            "scope": self.scope,
            "valid_from": (
                self.valid_from.isoformat() if self.valid_from else None
            ),
            "valid_to": (
                self.valid_to.isoformat() if self.valid_to else None
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
            "revoked_at": (
                self.revoked_at.isoformat() if self.revoked_at else None
            ),
            "revoked_by_user_guid": (
                str(self.revoked_by_user_guid)
                if self.revoked_by_user_guid else None
            ),
            "revoked_by_role": self.revoked_by_role,
            "revoked_reason": self.revoked_reason,
            "is_active": self.is_active(),
        }

    def __repr__(self) -> str:
        return (
            f"<PatientProxyGrant {self.guid} patient={self.patient_guid} "
            f"proxy={self.proxy_user_guid} active={self.is_active()}>"
        )
