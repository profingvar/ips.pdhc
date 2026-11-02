"""Derive and read the bitemporal patient-state projection. EPS C1 (#895).

`rebuild_for_patient()` is the whole write path: it deletes and re-derives.
That is what makes `patient_state_facts` a projection rather than a second
source of truth — if it is ever wrong, it is rebuilt, and nothing is lost
because nothing originates here.

## Where each axis comes from

    source                        validity                  record
    fhir_resources (Patient)      the element's `period`    version created_at,
                                  or NULL                   superseded by the NEXT
                                                            version's created_at
    patient_clinic_assignments    assigned_at / ended_at    assigned_at

**The two axes COINCIDE for a clinic assignment, and that is a limitation of
the source rather than of the model.** That table carries one timestamp, so
"when it began" and "when we wrote it down" cannot be told apart there. Said
out loud because a reader comparing the two columns would otherwise conclude
the model conflates them.

**Validity is NULL for every demographic fact today.** Measured 2026-11-02: the
generator writes no `period` on any Patient element — address is
`use`/`city`/`country`, telecom is `system`/`value`/`use`. NULL means *we do
not know when this became true*, which is a different claim from *it became
true when we recorded it*. Filling it from `recorded_at` would be the
single-axis mistake this projection exists to prevent, and it waits on #888
(EPS C2) adding real `Address.period`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment
from app.models.patient_state import FACT_TYPES, PatientStateFact


def _period(element: dict) -> tuple[datetime | None, datetime | None]:
    """(valid_from, valid_to) from a FHIR element's `period`, or (None, None).

    Never substitutes a record time for a missing validity bound.
    """
    p = element.get("period") if isinstance(element, dict) else None
    if not isinstance(p, dict):
        return None, None
    return _parse(p.get("start")), _parse(p.get("end"))


def _parse(v) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _facts_from_patient(pj: dict) -> list[tuple[str, dict, datetime | None, datetime | None]]:
    """Every state fact a Patient resource carries, with its validity."""
    out: list[tuple[str, dict, datetime | None, datetime | None]] = []
    names = pj.get("name") or []
    if isinstance(names, list) and names:
        n = names[0] if isinstance(names[0], dict) else {}
        vf, vt = _period(n)
        if n.get("family"):
            out.append(("name.family", {"value": n["family"]}, vf, vt))
        if n.get("given"):
            out.append(("name.given", {"value": n["given"]}, vf, vt))
    for addr in (pj.get("address") or []):
        if not isinstance(addr, dict):
            continue
        vf, vt = _period(addr)
        use = addr.get("use")
        for key in ("line", "city", "postalCode", "country"):
            if addr.get(key) not in (None, "", []):
                out.append((f"address.{key}",
                            {"value": addr[key], "use": use}, vf, vt))
    for tel in (pj.get("telecom") or []):
        if not isinstance(tel, dict):
            continue
        vf, vt = _period(tel)
        out.append(("telecom", {"system": tel.get("system"),
                                "value": tel.get("value"),
                                "use": tel.get("use")}, vf, vt))
    for con in (pj.get("contact") or []):
        if not isinstance(con, dict):
            continue
        vf, vt = _period(con)
        out.append(("contact", con, vf, vt))
    return [f for f in out if f[0] in FACT_TYPES]


def rebuild_for_patient(patient_guid) -> int:
    """Delete and re-derive every fact for one patient. Returns rows written.

    Deliberately destructive and total: a projection that is patched
    incrementally drifts from its sources, and then the only way to find out is
    to rebuild it anyway.
    """
    (db.session.query(PatientStateFact)
     .filter(PatientStateFact.patient_guid == patient_guid)
     .delete(synchronize_session=False))

    rows: list[PatientStateFact] = []

    # ----- demographics, from every version of the Patient resource -------
    versions = (db.session.query(FhirResource)
                .filter(FhirResource.resource_type == "Patient",
                        FhirResource.patient_guid == patient_guid)
                .order_by(FhirResource.version_id.asc())
                .all())
    for i, v in enumerate(versions):
        # Record time ends where the NEXT version's begins. This is the half
        # of bitemporality `fhir_resources` already gives us for free, because
        # `update_resource` writes a new row rather than mutating one.
        nxt = versions[i + 1] if i + 1 < len(versions) else None
        for fact_type, value, vf, vt in _facts_from_patient(v.resource_json or {}):
            rows.append(PatientStateFact(
                patient_guid=patient_guid, fact_type=fact_type, value=value,
                valid_from=vf, valid_to=vt,
                recorded_at=v.created_at,
                recorded_until=nxt.created_at if nxt else None,
                source_table="fhir_resources", source_guid=v.guid,
                source_version=v.version_id))

    # ----- clinic assignment, the one source with REAL validity data ------
    for a in (db.session.query(PatientClinicAssignment)
              .filter(PatientClinicAssignment.patient_guid == patient_guid)
              .order_by(PatientClinicAssignment.assigned_at.asc())
              .all()):
        rows.append(PatientStateFact(
            patient_guid=patient_guid, fact_type="clinic_assignment",
            value={"clinic_guid": str(a.clinic_guid)},
            valid_from=a.assigned_at, valid_to=a.ended_at,
            # One timestamp in the source, so the axes coincide here. A
            # limitation of the source, stated rather than hidden.
            recorded_at=a.assigned_at, recorded_until=None,
            source_table="patient_clinic_assignments", source_guid=a.guid,
            source_version=None))

    for r in rows:
        db.session.add(r)
    return len(rows)


def state_at(patient_guid, *, as_at: datetime | None = None,
             as_known_on: datetime | None = None) -> list[PatientStateFact]:
    """The patient's state as at `as_at`, as it was known on `as_known_on`.

    Both default to now, which gives "current state as we currently hold it" —
    the ordinary question. Pass both to answer the one a single axis cannot:
    *what did the register say in April about where the patient lived in
    March?*

    An unbounded validity bound (NULL) matches every date. That is the correct
    reading of "we do not know when this became true" — the alternative,
    excluding it, would return nothing for every patient whose data carries no
    period, which is all of them today. The NULL is returned to the caller
    rather than filled in, so nobody mistakes an unknown bound for a known one.
    """
    now = datetime.now(timezone.utc)
    at = as_at or now
    known = as_known_on or now
    q = (db.session.query(PatientStateFact)
         .filter(PatientStateFact.patient_guid == patient_guid)
         # validity contains `at`
         .filter(db.or_(PatientStateFact.valid_from.is_(None),
                        PatientStateFact.valid_from <= at))
         .filter(db.or_(PatientStateFact.valid_to.is_(None),
                        PatientStateFact.valid_to > at))
         # record interval contains `known`
         .filter(PatientStateFact.recorded_at <= known)
         .filter(db.or_(PatientStateFact.recorded_until.is_(None),
                        PatientStateFact.recorded_until > known))
         .order_by(PatientStateFact.fact_type, PatientStateFact.recorded_at))
    return q.all()
