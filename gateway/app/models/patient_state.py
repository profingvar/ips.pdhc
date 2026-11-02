"""Bitemporal projection of patient STATE. EPS C1 (#895).

Decided by #894 (EPS A2), option c: the write path stays `fhir_resources`,
append-only, which already exists — and this table is a DERIVED projection for
reading. It is rebuildable from its sources and is therefore not a second
source of truth, the same role `patient_index` already plays via
`_sync_patient_index()`.

## Why a projection at all

Validity time is not a uniform FHIR field. It is `Address.period`,
`Patient.contact.period`, `RelatedPerson.period`, `Condition.onset`/`abatement`
— each in a different place with a different name. So "state as at date D"
across resources means knowing every element's own period field, in
application code, every time. Uniform columns make that one query.

## Two axes, and they are NOT the same question

    axis           columns                        question
    validity       valid_from / valid_to          when was this TRUE of the patient?
    record         recorded_at / recorded_until   when did WE know it?

A patient moves in March and tells us in July. One axis cannot express "the
register was wrong between March and July", and that is the ordinary case for
an address. It also matters beyond tidiness: a spärr decision or an alert read
at a past date must be reconstructible AS IT WAS KNOWN THEN, not as it is known
now.

The vocabulary is already settled on this platform —
`alert.pdhc/app/models/assertion.py` carries `asserted_at` and `recorded_at`
side by side for exactly this reason.

## What is NOT in here, and why

**Diagnoses and alerts.** #894 ratified that they are REFERENCED, not owned:
`icd11.pdhc` is the authority for the diagnosis episode and its append-only
assertion log, `alert.pdhc` owns the selection logic and the
simulated-vs-real distinction that is the MDR-relevant surface. A third copy
here would be three sources with no stated precedence.

**Clinical section content**, which #791 put in `fhir_resources` and which this
does not move. State is not clinical content; that distinction is what makes
both decisions coherent rather than contradictory.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import db, new_uuid, utcnow, GUID, JSONB

#: The fact types this projection knows. A DECLARED vocabulary, not freeform:
#: a projection whose keys are whatever the projector happened to emit cannot
#: be queried by anyone who did not write the projector.
#:
#: Dotted, and the prefix is the FHIR element it came from, so a reader can get
#: back to the source shape without consulting this file.
FACT_TYPES: tuple[str, ...] = (
    "name.family",
    "name.given",
    "address.line",
    "address.city",
    "address.postalCode",
    "address.country",
    "telecom",
    "contact",
    "clinic_assignment",
    # #901(b): the four remaining state bearers. Each was one-ended in its own
    # table and each lands differently on the two axes — see
    # `services/patient_state` for the per-source mapping and what it reveals.
    "consent",
    "block",
    "block_lift",
    "emergency_access",
    "ehds_opt_out",
    "quality_registry_opt_out",
    "archived",
)


class PatientStateFact(db.Model):
    """One fact about a patient, true over a validity interval, as known over a
    record interval.

    1:N per patient and 1:1 per `(patient, fact_type, validity period)` — which
    is the correction the operator made to the original 1:1 framing. A patient
    has several addresses, several next-of-kin, and a history of each.
    """

    __tablename__ = "patient_state_facts"
    __table_args__ = (
        Index("ix_psf_patient_type", "patient_guid", "fact_type"),
        # The as-at read filters on validity and record intervals together, so
        # the index carries both lower bounds. Upper bounds are usually NULL
        # (still true / still current), which an index cannot help with and
        # does not need to.
        Index("ix_psf_valid_from", "patient_guid", "valid_from"),
        Index("ix_psf_recorded_at", "patient_guid", "recorded_at"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=new_uuid)
    patient_guid: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("patient_index.guid", ondelete="CASCADE"),
        nullable=False)
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: JSONB because several of these are structured — an address line is a
    #: list, a contact is a name plus a relationship plus a telecom. A text
    #: column would force every consumer to parse.
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # ----- validity: when was this TRUE of the patient -------------------
    #: NULL means **we do not know when this became true**, which is NOT the
    #: same as "it became true when we recorded it". Measured 2026-11-02: the
    #: generator writes no `period` on any Patient element, so for demographics
    #: this is NULL today and stays NULL until #888 (EPS C2) adds real
    #: `Address.period` data. Filling it from `recorded_at` would be the
    #: single-axis mistake this table exists to prevent.
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: NULL means still true. Not an expiry — see `ended_at` on
    #: patient_clinic_assignments for the same distinction.
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # ----- record: when did WE know it -----------------------------------
    #: From the source row's own creation. Never invented.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow)
    #: When this knowledge was superseded — the NEXT version's `created_at`.
    #: NULL means it is still what we hold.
    recorded_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # ----- provenance ----------------------------------------------------
    #: Which table and row this was derived from, so the projection can always
    #: be traced back and never has to be trusted on its own.
    source_table: Mapped[str] = mapped_column(String(64), nullable=False)
    source_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())
    source_version: Mapped[int | None] = mapped_column(Integer)

    def to_dict(self) -> dict:
        return {
            "fact_type": self.fact_type,
            "value": self.value,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "recorded_until": (self.recorded_until.isoformat()
                               if self.recorded_until else None),
            "source": {
                "table": self.source_table,
                "guid": str(self.source_guid) if self.source_guid else None,
                "version": self.source_version,
            },
        }
