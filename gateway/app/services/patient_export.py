"""Export selected patients as CSV or as a FHIR Bundle. EPS B7 (#896).

**Nothing like this existed.** Measured 2026-11-02 across ips, cdr and cdr_6:
no `/export` route, no CSV writer, no xlsx writer. So the access and audit
properties below had to be built rather than inherited, which is why they are
spelled out here instead of assumed.

## Access: the SAME relationship the spärr and consent gates use

The blast radius of an export is every access rule at once, so it must not pose
a new question. `exportable()` answers set-wise exactly what
`blocks_routes._can_act_on_patient` answers per patient:

    admin                    -> every requested patient
    anyone else              -> patients with an ACTIVE PatientClinicAssignment
                                to a clinic the reader is assigned to

"Active" since #899(b): a reader at a clinic the patient has LEFT is not a
reader of that patient. A test asserts the set filter and the per-patient gate
agree on every candidate, because "no two consumers may enforce different
rules" is the whole reason `care_access_policy` exists and an export is a
second consumer.

A patient the reader may not open individually is **absent** from the output
rather than reported as refused. Absent leaks no existence either — the same
reasoning as onboard's flat 404 on a bad invite token.

## An EXPLICIT gate, because the surrounding surface has a weaker one

`admin.py`'s `before_request` requires only an SSO SESSION — not
`is_su_admin`, not a phase. So an export placed there would inherit "any
authenticated user". This module therefore asks its own question and fails
closed, which is a tightening relative to its surroundings and the safe
direction. It does NOT rely on the blueprint's gate.

## Personnummer

**Excluded from the CSV.** A CSV leaves the system, `personnummer` is subject
to a hard confinement rule (#405), and no masking helper exists in this repo —
verified. The export keys on guid instead. The FHIR Bundle is a different case:
`Patient.identifier` is part of the document by design, so the Bundle carries
it and the CSV does not.

## The CSV shape is a decision, because state is 1:N with intervals

    as_at (default)   one row per (patient, fact_type) VALID at `as_at`,
                      as known now -- what people expect from a CSV
    history           one row per (patient, fact_type, period), with BOTH
                      time axes as columns

Column names say which axis they are. A single column called `date` here would
re-introduce exactly the conflation #895 exists to remove.

## The FHIR half is R5 and is NOT a conformance claim

#877 chose to export R5 rather than render R4, so this is *EPS-shaped content,
R5 serialisation*. #885 has since verified the CODES (`CODES_VERIFIED` is now
True, with `CODES_VERIFIED_AGAINST` recording which guides and when) — and that
changes nothing here, because verified codes are not conformance: the EPS guide
is a ballot, it is an R4 guide while this exports R5, and cardinality is
unchecked. The Bundle still carries a `meta.tag` saying so rather than leaving
a reader to assume. See #897 for why the version is a parameter even though only
R5 is implemented.
"""
from __future__ import annotations

import csv
import io
from copy import deepcopy
from datetime import datetime, timezone

from flask import g, session

from app.models.base import db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.services import patient_state

#: #797 generates up to 100 patients, so that is the realistic upper bound to
#: design for. Refused by NAME past the cap rather than left to time out: the
#: #833 lesson is that a permanent condition reported as transient tells the
#: caller to retry forever.
MAX_PATIENTS = 100


class ExportTooLarge(Exception):
    """More patients than the cap. A terminal condition, named as one."""


class ExportNotPermitted(Exception):
    """The reader may not export at all. Distinct from exporting nothing."""


class UnsupportedFhirVersion(Exception):
    """#897: the version is a parameter so adding R4 later is additive rather
    than a refactor. Only R5 is implemented, and asking for anything else is
    refused by name rather than silently answered in R5."""


def is_admin() -> bool:
    """Admin per the SSO blob, which is what the session actually carries.

    `g.current_user` is set on the API paths; the HTML admin surface carries
    `session["sso_user"]`. Both are checked so this one predicate works on
    either, rather than each caller picking one and getting it wrong.
    """
    u = getattr(g, "current_user", None)
    if u is not None and getattr(u, "is_superuser", False):
        return True
    return bool((session.get("sso_user") or {}).get("is_su_admin"))


def _reader_clinic_guids() -> list:
    u = getattr(g, "current_user", None)
    if u is None:
        return []
    return [r[0] for r in db.session.query(UserClinicAssignment.clinic_guid)
            .filter(UserClinicAssignment.user_guid == u.guid).all()]


def exportable(requested: list[str]) -> tuple[list[str], list[str]]:
    """(allowed, withheld) for `requested`, in the reader's own scope.

    Withheld guids are returned so the CALLER can be told a count, never a
    list — a count says "your selection was narrowed", a list would confirm
    which guids exist.
    """
    existing = {str(r[0]) for r in db.session.query(PatientIndex.guid)
                .filter(PatientIndex.guid.in_(requested or [None])).all()}
    if is_admin():
        allowed = {g_ for g_ in requested if g_ in existing}
    else:
        clinics = _reader_clinic_guids()
        if not clinics:
            allowed = set()
        else:
            rows = (PatientClinicAssignment.active_only(
                        db.session.query(PatientClinicAssignment.patient_guid)
                        .filter(PatientClinicAssignment.clinic_guid.in_(clinics)))
                    .filter(PatientClinicAssignment.patient_guid.in_(requested or [None]))
                    .all())
            allowed = {str(r[0]) for r in rows} & existing
    return sorted(allowed), sorted(set(requested) - allowed)


def _audit(allowed: list[str], *, fmt: str, mode: str) -> None:
    """One row per patient, never one per batch.

    An export of fifty patients writes fifty rows. A single "exported a batch"
    row makes the log useless for the only question anyone asks of it: who has
    seen this patient's data?
    """
    from app.services.audit_service import log_event
    for guid in allowed:
        log_event("patient.exported", patient_guid=guid,
                  detail={"format": fmt, "mode": mode,
                          "patients_in_export": len(allowed)})


CSV_AS_AT_COLUMNS = ["patient_guid", "fact_type", "value",
                     "valid_from", "valid_to", "source"]
CSV_HISTORY_COLUMNS = ["patient_guid", "fact_type", "value",
                       "valid_from", "valid_to",
                       "recorded_at", "recorded_until", "source"]


def to_csv(patient_guids: list[str], *, mode: str = "as_at",
           as_at: datetime | None = None) -> str:
    """CSV of patient STATE. No personnummer — see the module docstring."""
    if mode not in ("as_at", "history"):
        raise ValueError(f"unknown mode {mode!r}")
    out = io.StringIO()
    cols = CSV_AS_AT_COLUMNS if mode == "as_at" else CSV_HISTORY_COLUMNS
    w = csv.DictWriter(out, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for guid in patient_guids:
        if mode == "as_at":
            facts = patient_state.state_at(guid, as_at=as_at)
        else:
            from app.models.patient_state import PatientStateFact
            facts = (db.session.query(PatientStateFact)
                     .filter(PatientStateFact.patient_guid == guid)
                     .order_by(PatientStateFact.fact_type,
                               PatientStateFact.recorded_at).all())
        for f in facts:
            row = {
                "patient_guid": str(guid),
                "fact_type": f.fact_type,
                "value": str(f.value.get("value", f.value)),
                "valid_from": f.valid_from.isoformat() if f.valid_from else "",
                "valid_to": f.valid_to.isoformat() if f.valid_to else "",
                "source": f.source_table,
            }
            if mode == "history":
                row["recorded_at"] = (f.recorded_at.isoformat()
                                      if f.recorded_at else "")
                row["recorded_until"] = (f.recorded_until.isoformat()
                                         if f.recorded_until else "")
            w.writerow(row)
    return out.getvalue()


def to_fhir_bundle(patient_guids: list[str], *, version: str = "R5") -> dict:
    """A FHIR Bundle of the selected patients' current resources.

    R5 only (#877). The version is a parameter so adding an R4 renderer later
    is additive rather than a refactor (#897), and anything else is refused by
    name instead of being quietly answered in R5.
    """
    if version != "R5":
        raise UnsupportedFhirVersion(
            f"{version} is not implemented; this service exports R5 (#877). "
            f"An R4 render path is #884, closed as not-to-be-done, and #897 "
            f"records what it would cost.")
    entries = []
    for guid in patient_guids:
        for r in (db.session.query(FhirResource)
                  .filter(FhirResource.patient_guid == guid,
                          FhirResource.status == "active")
                  .order_by(FhirResource.resource_type,
                            FhirResource.resource_id).all()):
            # DEEP COPY, and this is not caution — it is a defect #897 named
            # in advance and #896 shipped anyway. `r.resource_json` is the ORM
            # object's own dict: putting it in the bundle by reference means a
            # caller mutating the bundle mutates the STORED resource, and if
            # that object is then flushed the mutation is PERSISTED. Measured:
            # setting a key on the entry appeared on `res.resource_json`.
            #
            # It is also the precondition for ever adding an R4 renderer
            # (#897): a downgrade that edits in place would corrupt the R5
            # output it was derived from.
            entries.append({"fullUrl": f"{r.resource_type}/{r.resource_id}",
                            "resource": deepcopy(r.resource_json)})
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(entries),
        # Said IN the document, not in a docstring: a recipient must not read
        # this as an EPS conformance claim. #885 verified the codes; it did
        # not and could not verify conformance — the EPS guide is a ballot and
        # is R4, while this is R5.
        "meta": {"tag": [{
            "system": "https://ips.pdhc.se/export",
            "code": "not-eps-conformant",
            "display": ("EPS-shaped content, FHIR R5 serialisation. All "
                        "required sections present is the only claim made; "
                        "EPS is R4 and the section codes are unverified "
                        "against the published IG."),
        }]},
        "entry": entries,
    }


def export(requested: list[str], *, fmt: str, mode: str = "as_at",
           as_at: datetime | None = None, version: str = "R5") -> dict:
    """The one entry point. Filters, caps, renders and audits, in that order.

    Order matters: nothing is rendered for a patient the reader may not have,
    and nothing is audited that was not rendered.
    """
    if not isinstance(requested, list) or not requested:
        raise ValueError("patient_guids must be a non-empty list")
    if len(requested) > MAX_PATIENTS:
        raise ExportTooLarge(
            f"{len(requested)} patients requested; the cap is {MAX_PATIENTS}. "
            f"Split the selection.")
    if not is_admin() and not _reader_clinic_guids():
        raise ExportNotPermitted(
            "no clinic assignment, so no patient is in scope for this reader")

    allowed, withheld = exportable(requested)
    if fmt == "csv":
        body = to_csv(allowed, mode=mode, as_at=as_at)
        content_type = "text/csv"
    elif fmt == "fhir":
        body = to_fhir_bundle(allowed, version=version)
        content_type = "application/fhir+json"
    else:
        raise ValueError(f"unknown format {fmt!r}")

    _audit(allowed, fmt=fmt, mode=mode)
    return {"body": body, "content_type": content_type,
            "exported": len(allowed), "withheld": len(withheld)}
