"""#797 — generation batches: identify, count and purge.

Operator request: "be able to fill in each header for up to 100 patients for an
assigned care provider". Generating is the easy half; being able to UNDO it is
what makes it usable more than once.

#791 added `patient_index.generation_batch_guid` for exactly this, because
there was no batch or run marker at all and removing a batch meant recording
its GUIDs by hand. sim.pdhc solved the same problem with a run id and
`sim purge`; this follows that shape.

## The delete order is not obvious, and getting it wrong loses data

The foreign keys here cascade in a direction that surprises:

* `ips_cards.patient_guid` -> `patient_index` ON DELETE CASCADE, and
  `ips_snapshots.card_guid` -> `ips_cards` CASCADE. So deleting a patient takes
  its cards and snapshots with it. Good.
* `patient_clinic_assignments.patient_guid` -> `patient_index` CASCADE. Good.
* **`patient_index.fhir_resource_guid` -> `fhir_resources` ON DELETE CASCADE.**
  That is the surprising one: it points the OTHER way. Deleting the Patient's
  FhirResource row cascade-deletes the PatientIndex. So resources must be
  deleted AFTER the patients, or the cascade fires while we are still reading
  the patient list.
* `fhir_resources.patient_guid` has **no FK at all** — it is a plain GUID
  column (Rule 18). So clinical resources are never cascaded and must be
  deleted explicitly. A purge that relies on cascades alone leaves every
  Condition, Observation and AllergyIntolerance orphaned, pointing at a
  patient that no longer exists.

Hence: collect the guids first, delete `patient_index`, then delete
`fhir_resources` by both `patient_guid` and the Patient resources' own guids.
"""
from __future__ import annotations

import uuid

from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import euips_sections as euips


def list_batches() -> list[dict]:
    """Every generation batch, newest first, with its counts.

    Derived, not stored: the timestamp is `created_at` and the organisation
    comes from the clinic assignment, so a batch table would only duplicate
    facts already present — the reasoning #791 recorded.
    """
    rows = (db.session.query(PatientIndex)
            .filter(PatientIndex.generation_batch_guid.isnot(None))
            .all())
    by_batch: dict[uuid.UUID, list[PatientIndex]] = {}
    for p in rows:
        by_batch.setdefault(p.generation_batch_guid, []).append(p)

    out = []
    for batch, patients in by_batch.items():
        guids = [p.guid for p in patients]
        resources = (db.session.query(FhirResource)
                     .filter(FhirResource.patient_guid.in_(guids)).count())
        # The clinic is the same for a whole batch by construction, so the
        # first assignment answers for all of them.
        clinic_name = None
        assignment = (db.session.query(PatientClinicAssignment)
                      .filter(PatientClinicAssignment.patient_guid == guids[0])
                      .first())
        if assignment:
            clinic = (db.session.query(Clinic)
                      .filter(Clinic.guid == assignment.clinic_guid).first())
            clinic_name = clinic.name if clinic else None
        created = min((p.created_at for p in patients if p.created_at),
                      default=None)
        out.append({
            "batch_guid": str(batch),
            "patients": len(patients),
            "resources": resources,
            "clinic": clinic_name,
            "created_at": created.isoformat() if created else None,
            "conformant": conformant_count(guids),
        })
    out.sort(key=lambda b: b["created_at"] or "", reverse=True)
    return out


def conformant_count(patient_guids) -> int:
    """How many of these patients are euIPS-conformant.

    "Fill in each header" means every required section present or explicitly
    absent, so the operator should see 100/100 rather than infer it.
    """
    n = 0
    for guid in patient_guids:
        rows = (db.session.query(FhirResource)
                .filter(FhirResource.patient_guid == guid).all())
        if euips.is_conformant(euips.status_for_resources(rows)):
            n += 1
    return n


def batch_preview(batch_guid: str) -> dict | None:
    """What a purge WOULD delete. No writes.

    Separate from the purge itself so the operator sees the counts before
    agreeing to them -- the same compare-then-write shape the deploy scripts
    use, and for the same reason.
    """
    try:
        batch = uuid.UUID(str(batch_guid))
    except (ValueError, TypeError):
        return None
    patients = (db.session.query(PatientIndex)
                .filter(PatientIndex.generation_batch_guid == batch).all())
    if not patients:
        return None
    guids = [p.guid for p in patients]
    resource_guids = [p.fhir_resource_guid for p in patients]
    clinical = (db.session.query(FhirResource)
                .filter(FhirResource.patient_guid.in_(guids)).count())
    patient_resources = (db.session.query(FhirResource)
                         .filter(FhirResource.guid.in_(resource_guids)).count())
    assignments = (db.session.query(PatientClinicAssignment)
                   .filter(PatientClinicAssignment.patient_guid.in_(guids))
                   .count())
    cards = (db.session.query(IpsCard)
             .filter(IpsCard.patient_guid.in_(guids)).count())
    card_guids = [c.guid for c in db.session.query(IpsCard)
                  .filter(IpsCard.patient_guid.in_(guids)).all()]
    snapshots = ((db.session.query(IpsSnapshot)
                  .filter(IpsSnapshot.card_guid.in_(card_guids)).count())
                 if card_guids else 0)
    return {
        "batch_guid": str(batch),
        "patients": len(patients),
        "clinical_resources": clinical,
        "patient_resources": patient_resources,
        "clinic_assignments": assignments,
        "ips_cards": cards,
        "ips_snapshots": snapshots,
    }


def purge_batch(batch_guid: str) -> dict | None:
    """Delete a whole batch. Returns what was removed, or None if unknown.

    Order matters -- see the module docstring. In particular
    `fhir_resources.patient_guid` has no foreign key, so the clinical
    resources are NOT cascaded and would be left orphaned by a
    patients-only delete.
    """
    preview = batch_preview(batch_guid)
    if preview is None:
        return None
    batch = uuid.UUID(str(batch_guid))

    patients = (db.session.query(PatientIndex)
                .filter(PatientIndex.generation_batch_guid == batch).all())
    guids = [p.guid for p in patients]
    resource_guids = [p.fhir_resource_guid for p in patients]

    # 1. Dependents EXPLICITLY, deepest first, rather than relying on the
    #    declared ON DELETE CASCADE.
    #
    #    Not belt-and-braces: the first version of this trusted the cascades
    #    and left 8 of 8 patient_clinic_assignments behind in tests. The FKs do
    #    declare CASCADE, and PostgreSQL honours them -- but SQLite does not
    #    enforce foreign keys unless `PRAGMA foreign_keys=ON`, and the test
    #    database is SQLite. So the purge would have worked in production and
    #    leaked in tests, which is the #730 shape exactly: a test engine that
    #    behaves differently from the real one hides the defect rather than
    #    showing it.
    #
    #    An explicit delete is identical on both and does not depend on FK
    #    enforcement being switched on anywhere.
    card_guids = [c.guid for c in db.session.query(IpsCard)
                  .filter(IpsCard.patient_guid.in_(guids)).all()]
    if card_guids:
        (db.session.query(IpsSnapshot)
         .filter(IpsSnapshot.card_guid.in_(card_guids))
         .delete(synchronize_session=False))
    (db.session.query(IpsCard)
     .filter(IpsCard.patient_guid.in_(guids))
     .delete(synchronize_session=False))
    (db.session.query(PatientClinicAssignment)
     .filter(PatientClinicAssignment.patient_guid.in_(guids))
     .delete(synchronize_session=False))

    # 2. Then the patients. Before the resource delete, because
    #    patient_index.fhir_resource_guid -> fhir_resources CASCADES THE OTHER
    #    WAY and would remove these rows from under us.
    (db.session.query(PatientIndex)
     .filter(PatientIndex.generation_batch_guid == batch)
     .delete(synchronize_session=False))

    # 3. Then the clinical resources, which no FK protects or cascades.
    (db.session.query(FhirResource)
     .filter(FhirResource.patient_guid.in_(guids))
     .delete(synchronize_session=False))

    # 4. And the Patient resources themselves.
    (db.session.query(FhirResource)
     .filter(FhirResource.guid.in_(resource_guids))
     .delete(synchronize_session=False))

    db.session.commit()
    return preview
