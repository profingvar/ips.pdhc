"""Assign a patient to a clinic, and END an assignment. EPS C4c (#900).

#891 gave `patient_clinic_assignments` an `ended_at` and a partial unique
index; #899(b) made spärr, consent and care access honour it; #901 made the
state projection follow it. **Nothing could SET it.** A column nothing
populates is the shape this module exists to close, and until now the whole
chain guarded a state that never occurred.

## Two operations, not one

    assign(patient, clinic)   refuses if an OPEN assignment already exists
    end(patient, clinic)      refuses if there is no open assignment

The partial unique index `uq_patient_clinic_active` permits a CLOSED row and a
new OPEN one for the same pair, so "left and came back" is expressible — proven
against real Postgres in #891. `assign` therefore has to distinguish "already
assigned" from "assigned before and left", and it refuses only the first.

**The refusal is a named error, not an IntegrityError.** Letting the database
raise would reach the caller as a 500 with a constraint name in it, which tells
them nothing about what to do.

## This is the platform's FIRST writer of validity time

`ended_at` is a VALIDITY end — when the assignment stopped being true of the
patient — not a record time. So `end()` accepts a date and defaults to now,
because an assignment ending is usually learned after the fact and backdating
is the ordinary case, not an edge one.

It does NOT quietly use `utcnow()` only. That is the single-axis mistake #895
exists to prevent, and this route is where the platform first has to have an
opinion about it.

Two bounds follow from that, and both are refusals rather than silent
coercions:

* **`ended_at` before `assigned_at` is refused.** An interval that ends before
  it begins is not a bad date, it is an impossible fact.
* **A FUTURE `ended_at` is refused.** A planned future end is an EXPIRY, and
  #891's model note is explicit that `ended_at` is not `expires_at`: an expiry
  in the future means "still valid", while a non-NULL `ended_at` always means
  "over". Accepting a future date here would make that distinction false for
  every consumer that reads it.

## Ending an assignment REMOVES access

After #899(b), ending the last assignment to a clinic removes spärr, consent
and care access for every staff member there. That is the point, and it is why
each operation writes an audit row saying what it did and when it took effect —
`audit_log` already carries `patient_guid` with an index.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import g, session

from app.models.base import db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.services.audit_service import log_event
from app.services.patient_state import rebuild_for_patient


class AlreadyAssigned(Exception):
    """An OPEN assignment to that clinic already exists."""


class NotAssigned(Exception):
    """There is no open assignment to end."""


class ImpossibleInterval(Exception):
    """`ended_at` before `assigned_at`, or in the future."""


class NotPermitted(Exception):
    """The actor may not change this patient's assignment to this clinic."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_ok(a: datetime, b: datetime) -> bool:
    """Compare two datetimes that may differ in tz-awareness.

    SQLite stores no timezone, so a value read back is naive while
    `datetime.now(timezone.utc)` is aware, and comparing them raises. Production
    is Postgres with TIMESTAMPTZ where both are aware. Normalising here keeps
    the RULE identical on both backends instead of being accidentally skipped
    on one — the #895 lesson, where a tz mismatch silently corrupted a
    comparison rather than failing.
    """
    an = a.replace(tzinfo=None) if a.tzinfo else a
    bn = b.replace(tzinfo=None) if b.tzinfo else b
    return an <= bn


def may_change(patient_guid, clinic_guid) -> bool:
    """May the actor change THIS patient's assignment to THIS clinic?

    Admin, or a reader assigned to the clinic being changed. Deliberately
    narrower than "may see the patient": ending an assignment removes access
    for everyone at that clinic, so being able to read a patient is not reason
    enough to detach them from a clinic you have nothing to do with.
    """
    u = getattr(g, "current_user", None)
    if u is not None and getattr(u, "is_superuser", False):
        return True
    if (session.get("sso_user") or {}).get("is_su_admin"):
        return True
    if u is None:
        return False
    return db.session.query(
        db.session.query(UserClinicAssignment)
        .filter(UserClinicAssignment.user_guid == u.guid,
                UserClinicAssignment.clinic_guid == clinic_guid)
        .exists()).scalar()


def _open(patient_guid, clinic_guid):
    return PatientClinicAssignment.active_only(
        db.session.query(PatientClinicAssignment)
        .filter(PatientClinicAssignment.patient_guid == patient_guid,
                PatientClinicAssignment.clinic_guid == clinic_guid)).first()


def assign(patient_guid, clinic_guid, *, assigned_at: datetime | None = None):
    """Open an assignment. Refuses if one is already open for this pair."""
    if not may_change(patient_guid, clinic_guid):
        raise NotPermitted("not assigned to that clinic")
    if db.session.get(PatientIndex, patient_guid) is None:
        raise NotAssigned("no such patient")
    if db.session.get(Clinic, clinic_guid) is None:
        raise NotAssigned("no such clinic")
    if _open(patient_guid, clinic_guid) is not None:
        # NOT an IntegrityError: the database would refuse this too, via
        # uq_patient_clinic_active, but as a 500 carrying a constraint name.
        raise AlreadyAssigned(
            "this patient already has an open assignment to this clinic; "
            "end it before assigning again")
    row = PatientClinicAssignment(
        patient_guid=patient_guid, clinic_guid=clinic_guid,
        **({"assigned_at": assigned_at} if assigned_at else {}))
    db.session.add(row)
    db.session.flush()
    log_event("patient.assigned", patient_guid=patient_guid,
              detail={"clinic_guid": str(clinic_guid),
                      "assigned_at": row.assigned_at.isoformat()
                      if row.assigned_at else None})
    rebuild_for_patient(patient_guid)
    return row


def end(patient_guid, clinic_guid, *, ended_at: datetime | None = None):
    """Close the open assignment for this pair.

    `ended_at` is a VALIDITY end and defaults to now. A past date is accepted
    because learning of a move after the fact is ordinary; a future date is
    refused because that would be an expiry, which `ended_at` is not.
    """
    if not may_change(patient_guid, clinic_guid):
        raise NotPermitted("not assigned to that clinic")
    row = _open(patient_guid, clinic_guid)
    if row is None:
        raise NotAssigned(
            "no open assignment to this clinic; it may already have ended")

    when = ended_at or _now()
    if row.assigned_at is not None and not _naive_ok(row.assigned_at, when):
        raise ImpossibleInterval(
            f"ended_at {when.isoformat()} is before assigned_at "
            f"{row.assigned_at.isoformat()}: an interval cannot end before it "
            f"begins")
    if not _naive_ok(when, _now()):
        raise ImpossibleInterval(
            "ended_at is in the future. `ended_at` records an end that "
            "HAPPENED; a planned future end is an expiry, and #891's model "
            "note is explicit that the two are not interchangeable")

    row.ended_at = when
    db.session.flush()
    log_event("patient.assignment_ended", patient_guid=patient_guid,
              detail={"clinic_guid": str(clinic_guid),
                      "ended_at": when.isoformat(),
                      "backdated": ended_at is not None,
                      # Said in the audit row because it is the consequence
                      # someone reading the log will care about (#899b).
                      "effect": ("staff at this clinic lose spärr, consent "
                                 "and care access for this patient")})
    rebuild_for_patient(patient_guid)
    return row
