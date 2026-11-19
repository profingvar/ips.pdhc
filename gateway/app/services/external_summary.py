"""The de-identified IPS summary an external read grant may see (2026-11-19).

Called by the CDRs' external read door (cdr.pdhc `/external/v1/...`) for the
patients a time-limited read grant covers. It returns, per patient, ONLY:

  * the platform patient GUID (the operator's decision: the real GUID, so the
    recipient can join across CDRs -- which also means this is PSEUDONYMISED,
    not anonymous, data in the GDPR sense);
  * sex (`gender`) and birth YEAR -- never the date;
  * diagnoses (Condition) and medications (MedicationStatement /
    MedicationRequest) as CODES: system, code, display, plus status and dates.

Never the personnummer, a name, an address, a free-text note or `text`, or
anything else in resource_json. Built by picking known fields out, not by
deleting known-bad ones, so a field added to the source later stays out.
"""
from __future__ import annotations

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex

MAX_PATIENTS = 1000
_MED_TYPES = ("MedicationStatement", "MedicationRequest")


def _codings(cc) -> list[dict]:
    out = []
    for c in (cc or {}).get("coding") or []:
        if isinstance(c, dict) and c.get("code"):
            out.append({k: c.get(k) for k in ("system", "code", "display")
                        if c.get(k) is not None})
    return out


def _status(cc) -> str | None:
    codes = _codings(cc)
    return codes[0]["code"] if codes else None


def _condition(r: dict) -> dict | None:
    codes = _codings(r.get("code"))
    if not codes:
        return None
    ver = _status(r.get("verificationStatus"))
    if ver == "entered-in-error":
        return None
    return {"code": codes,
            "clinical_status": _status(r.get("clinicalStatus")),
            "verification_status": ver,
            "onset": r.get("onsetDateTime") or (r.get("onsetPeriod") or {}).get("start"),
            "abatement": r.get("abatementDateTime"),
            "recorded": r.get("recordedDate")}


def _medication(r: dict) -> dict | None:
    # R4 medicationCodeableConcept, R5 medication.concept
    cc = r.get("medicationCodeableConcept") or (r.get("medication") or {}).get("concept")
    codes = _codings(cc)
    if not codes:
        return None
    period = r.get("effectivePeriod") or {}
    return {"code": codes,
            "resource_type": r.get("resourceType"),
            "status": r.get("status"),
            "start": r.get("effectiveDateTime") or period.get("start") or r.get("authoredOn"),
            "end": period.get("end")}


def summarise(patient_guids: list[str]) -> list[dict]:
    """One entry per KNOWN patient, in the order asked. Unknown guids are left
    out (the caller learns nothing more than that ips has no such patient)."""
    rows = (db.session.query(PatientIndex)
            .filter(PatientIndex.guid.in_(patient_guids)).all())
    by_guid = {str(p.guid): p for p in rows}
    res = (db.session.query(FhirResource)
           .filter(FhirResource.patient_guid.in_(list(by_guid)),
                   FhirResource.resource_type.in_(("Condition",) + _MED_TYPES))
           .all()) if by_guid else []
    conds: dict[str, list] = {g: [] for g in by_guid}
    meds: dict[str, list] = {g: [] for g in by_guid}
    for r in res:
        if (r.status or "active") == "deleted":
            continue
        g = str(r.patient_guid)
        j = r.resource_json or {}
        if r.resource_type == "Condition":
            c = _condition(j)
            if c:
                conds[g].append(c)
        else:
            m = _medication(j)
            if m:
                meds[g].append(m)
    out = []
    for g in patient_guids:
        p = by_guid.get(str(g))
        if p is None:
            continue
        out.append({"patient_guid": str(p.guid),
                    "sex": p.gender,
                    "birth_year": p.birth_date.year if p.birth_date else None,
                    "conditions": conds[str(p.guid)],
                    "medications": meds[str(p.guid)]})
    return out
