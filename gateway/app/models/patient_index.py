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
