"""Patient index and patient-clinic assignment models."""

import uuid
from datetime import datetime, date

from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import db, new_uuid, utcnow, GUID, JSONB


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

    # --- Access-model reform D1 (#404): patient opt-outs ----------------
    # These are the two consent flags with NO pre-existing model. The other
    # two consents from the v3 spec are already modelled richer here and are
    # NOT duplicated as new columns:
    #   allow_sharing_in_care  -> existing PatientConsent (per-caregiver
    #     cohesive-care consent, Lag 2022:913 §5 — more precise than a global
    #     bool; the reform's "allow_sharing" = "has an active PatientConsent
    #     for the relevant caregiver").
    #   primary_care_unit_guids -> existing PatientClinicAssignment rows.
    # ehds_opt_out: EHDS secondary-use opt-out; honoured at Analysis phase.
    ehds_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # quality_registry_opt_out: PDL kap 7; honoured by the Quality-registry-
    # reporter role before any external report.
    quality_registry_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # consented_research_projects: per-study research consent — list of
    # ResearchProject GUIDs (registry in sso.pdhc, S4). Intersected with the
    # researcher's affiliation research_project_guids at analysis read time
    # (v3 spec §5.3). JSONB list; a per-project table with revocation audit is
    # the upgrade path if needed.
    consented_research_projects: Mapped[list | None] = mapped_column(JSONB)

    # --- euIPS reform (#791): the ONE schema addition the reform needs ------
    # Generating "up to 100 patients for an assigned care provider" has to be
    # undoable. There was no batch or run marker on this table, so removing a
    # batch meant recording its GUIDs by hand. sim.pdhc solved the same problem
    # with a run id and `sim purge`.
    #
    # Nullable, no default, no index yet: the 150 existing rows keep NULL, and
    # nine sibling services read this table — `analysis-filter` alone is read by
    # cdr, cdr_6, analyse, dashboard and rosetta — so every change here is
    # additive by rule. Nothing else about the batch needs storing: the
    # timestamp is `created_at` and the organisation comes from the clinic
    # assignment, so a second table would only duplicate derivable facts.
    generation_batch_guid: Mapped[uuid.UUID | None] = mapped_column(GUID())

    # --- Admin-list archive (#811) -----------------------------------------
    # "Do not delete, retain searchability etc but do not list it."
    #
    # A SEPARATE column, deliberately NOT a reuse of `is_active` above, even
    # though that bool looks like it already means this. `is_active` is FHIR
    # `Patient.active` and is already load-bearing on a CROSS-SERVICE endpoint:
    # `clinic_routes.py` filters `PatientIndex.is_active.is_(True)` on
    # GET /api/v1/clinics/<guid>/patients -- the roster sim.pdhc builds cohorts
    # from. Overloading it would silently make "archive" also mean "drop from
    # every org-scoped roster and stop receiving generated data", which is a
    # much larger decision than hiding a row from one admin table.
    #
    # A timestamp rather than a bool: it answers "archived?" and "when?" for
    # the same storage, and a NULL is unambiguously "not archived". Nullable,
    # no default, additive -- the rule this table is held to, because nine
    # sibling services read it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
            # #791: additive. Existing keys are untouched -- sim.pdhc reads
            # this dict via GET /api/v1/clinics/<guid>/patients.
            "generation_batch_guid": (str(self.generation_batch_guid)
                                      if self.generation_batch_guid else None),
            "family_name": self.family_name,
            "given_name": self.given_name,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "gender": self.gender,
            "is_active": self.is_active,
            # #811: additive. Consumers that do not know about archiving
            # behave exactly as before -- archiving does NOT remove a patient
            # from any API response, only from the default admin list.
            "archived_at": (self.archived_at.isoformat()
                            if self.archived_at else None),
            "ehds_opt_out": self.ehds_opt_out,
            "quality_registry_opt_out": self.quality_registry_opt_out,
            "consented_research_projects": self.consented_research_projects or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def primary_care_unit_guids(self) -> list:
        """The patient's care units (Zone-1 inner circle) = the clinics they
        are assigned to (existing PatientClinicAssignment). Reform D1 models
        this via the existing assignment rows rather than a new column."""
        return [str(a.clinic_guid) for a in self.clinic_assignments]


#: Every site that joins `patient_clinic_assignments`, and what honouring
#: `ended_at` would MEAN there. #891 adds the column and the rule; it flips only
#: the unambiguous consumer, because these ten sites do not ask the same
#: question and three of them are authorisation.
#:
#: Flipping an authorisation path from "has an assignment" to "has an ACTIVE
#: assignment" is a TIGHTENING: staff at a clinic the patient has left would
#: lose access. That is almost certainly right, and it is still a security
#: change that needs its own verification rather than riding along with a
#: column addition.
CONSUMERS_OF_ASSIGNMENT = {
    # site                                      -> decision
    "api/clinic_routes.py roster":              "ACTIVE ONLY (#891) — a patient who left must not appear in a cohort",
    "api/blocks_routes.py staff authorisation": "ACTIVE ONLY (#899) — spärr. Flipped while it was provably a no-op",
    "api/consents_routes.py staff authorisation": "ACTIVE ONLY (#899) — consent access",
    "api/care_access_routes.py":                "ACTIVE ONLY (#899) — care access; None is a denial",
    "api/patient_routes.py the patient's clinics": "OPEN QUESTION — is it 'where they are' or 'where they have been'?",
    "api/patient_routes.py patient list filter": "OPEN QUESTION — an org-scoped list probably wants active only",
    "services/ips_generator.py managing org":   "PROBABLY HISTORICAL — a document generated then should keep the clinic current THEN; that is bitemporal and belongs with #895",
    "services/euips_batch.py preview/purge":    "ALL ROWS — bookkeeping about generated batches, not about current care",
    "services/mock_generator.py write":         "writes only",
    "admin.py write":                           "writes only",
}


class PatientClinicAssignment(db.Model):
    """Which clinic a patient belongs to, and SINCE WHEN — and now UNTIL when.

    #891 (EPS C4). Before it, this table had `assigned_at` and no end, so a
    patient who moved clinic was either still assigned to the old one or had no
    record of ever having been: there was no third thing the schema could say.
    That is not theoretical — `GET /api/v1/clinics/<guid>/patients` reads this
    table and sim.pdhc builds cohorts from it, so a stale assignment puts a
    patient in a cohort they left, and deleting the row loses that they were
    ever there.

    **The unique constraint had to change for the end date to mean anything.**
    `UniqueConstraint(patient_guid, clinic_guid)` made "ended" a TERMINAL state
    per pair: a patient returning to a clinic they had left could not be
    re-assigned, because the historical row still occupied the pair. It is now
    a PARTIAL unique index over active rows only — at most one open assignment
    per (patient, clinic), and any number of closed ones. For every row that
    exists today (all `ended_at IS NULL`) the rule is identical to the old
    constraint, so nothing currently stored is affected.
    """

    __tablename__ = "patient_clinic_assignments"
    __table_args__ = (
        # Replaces UniqueConstraint(patient_guid, clinic_guid) — see the class
        # docstring. Both dialects are given the predicate explicitly: with
        # only `postgresql_where`, SQLite (the test database) would build a
        # FULL unique index and silently forbid the second row, so the
        # behaviour under test would not be the behaviour in production.
        Index(
            "uq_patient_clinic_active",
            "patient_guid", "clinic_guid",
            unique=True,
            postgresql_where=db.text("ended_at IS NULL"),
            sqlite_where=db.text("ended_at IS NULL"),
        ),
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
    #: When the assignment ENDED. NULL = still active, which is every existing
    #: row, so this column changes nothing about what any consumer currently
    #: sees until that consumer opts in via `active_only()`.
    #:
    #: NOT a reuse of `expires_at`, which exists on patient_block,
    #: patient_consent, emergency_access and api_key. Those are EXPIRIES — a
    #: planned future end, set when the row is created. This is an end that
    #: HAPPENED, set when it happens, and the two are not interchangeable: an
    #: expiry in the future means "still valid", while a non-NULL `ended_at`
    #: always means "over".
    #:
    #: This is also one axis, not two. #895 (EPS C1) adds validity time beside
    #: record time for state generally; `ended_at` here is the validity END of
    #: one fact and `assigned_at` its validity START. There is deliberately no
    #: `recorded_at` yet — adding it belongs with the projection in C1 rather
    #: than piecemeal here, and `created_at` is not it.
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None)

    patient = relationship("PatientIndex", back_populates="clinic_assignments")
    clinic = relationship("Clinic")

    @classmethod
    def active_only(cls, query):
        """Narrow `query` to assignments that have not ended.

        THE SINGLE SOURCE OF THAT RULE, for the same reason
        `care_access_policy` is the single source of the zone rule: ten read
        sites join this table, three of them on authorisation paths, and two
        consumers applying different definitions of "assigned" is how a
        patient is visible to one surface and invisible to another.

        Consumers opt in. See `CONSUMERS_OF_ASSIGNMENT` in this module for the
        inventory and why each site has not simply been flipped.
        """
        return query.filter(cls.ended_at.is_(None))
