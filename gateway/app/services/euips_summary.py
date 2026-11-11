"""#980 — a LIVE euIPS summary: each section's status AND its entries.

`GET /<guid>/euips-sections` already answers, per section, PRESENT /
EXPLICITLY_ABSENT / MISSING, computed from the patient's `fhir_resources` on
every call. What it does not return is the CONTENT — the allergies, the
medications. The patient dashboard's card needs that, read live: the frozen
snapshot it could otherwise use was declined because older snapshots predate
#793 and can still be non-conformant.

THIS IS NOT A NEW COMPOSER, AND THAT IS THE POINT. #980 was filed believing a
composer had to be written, because `required_sections_for()` is a generator.
Measured: every section's resources are already written to `fhir_resources`
(the generator calls `create_resource` for each), and `euips_sections`
already classifies them. So this module reuses `section_matches` — which
DISCRIMINATES, because Condition is shared by three sections and Observation
by seven, and without discrimination a single vital sign made all seven read
PRESENT — and collects the rows instead of counting them.

THE THREE STATES ARE INHERITED, NOT REINVENTED. A section is PRESENT,
EXPLICITLY_ABSENT (an `absent-unknown-uv-ips` assertion, e.g. "no known
allergies") or MISSING (nothing at all). `status_for_resources` decides, and
real content wins over a stale absent assertion; the entries returned here
follow the same rule, so the two answers can never disagree.

A FOURTH STATE BELONGS TO THE CALLER, not here: "the summary could not be
read". This module reads its own database; a consumer that cannot reach ips
must report that by name rather than render an empty summary.

NOTHING IS DEDUPLICATED. Production holds one patient with the same atrial
fibrillation `Condition` twice (#984). Collapsing it here would hide a data
defect inside a presentation layer.
"""
from __future__ import annotations

import re
from typing import Any

from app.services import euips_sections as euips

#: The field that says WHAT a resource is, per type. R4 and R5 spellings both,
#: because the store holds both (DeviceUseStatement and DeviceUsage coexist).
_CONCEPT_FIELDS: dict[str, tuple[str, ...]] = {
    "AllergyIntolerance": ("code",),
    "Condition": ("code",),
    "MedicationStatement": ("medicationCodeableConcept", "medication"),
    "MedicationRequest": ("medicationCodeableConcept", "medication"),
    "Immunization": ("vaccineCode",),
    "Procedure": ("code",),
    "Device": ("type", "deviceName"),
    "DeviceUsage": ("device",),
    "DeviceUseStatement": ("device",),
    "DiagnosticReport": ("code",),
    "Observation": ("code",),
    "ClinicalImpression": ("code", "description"),
    "CarePlan": ("title", "category"),
    "Consent": ("category", "scope"),
    "Flag": ("code",),
    "QuestionnaireResponse": ("questionnaire",),
}

#: When it happened, first match wins.
_DATE_FIELDS = ("onsetDateTime", "recordedDate", "effectiveDateTime",
                "occurrenceDateTime", "performedDateTime", "authoredOn",
                "dateAsserted", "issued", "date", "authored")

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _concept(value: Any) -> tuple[str | None, str | None, str | None]:
    """Any FHIR "what" field -> (display, code, system). Tolerant of shape:
    a CodeableConcept, an R5 CodeableReference ({concept: ...}), a list, a
    Reference with a display, or a bare string."""
    if value is None:
        return None, None, None
    if isinstance(value, str):
        return value, None, None
    if isinstance(value, list):
        return _concept(value[0]) if value else (None, None, None)
    if isinstance(value, dict):
        if "concept" in value:                       # R5 CodeableReference
            return _concept(value["concept"])
        coding = (value.get("coding") or [None])[0] or {}
        display = (value.get("text") or coding.get("display")
                   or value.get("display") or value.get("name"))
        return display, coding.get("code"), coding.get("system")
    return None, None, None


def _date(rj: dict) -> str | None:
    for f in _DATE_FIELDS:
        v = rj.get(f)
        if isinstance(v, str) and v:
            return v
    for f in ("effectivePeriod", "performedPeriod", "period"):
        start = (rj.get(f) or {}).get("start")
        if start:
            return start
    return None


def _status(rj: dict) -> str | None:
    cs = rj.get("clinicalStatus")
    if cs:
        return _concept(cs)[1] or _concept(cs)[0]
    s = rj.get("status")
    return s if isinstance(s, str) else None


def _value(rj: dict) -> tuple[Any, str | None]:
    q = rj.get("valueQuantity")
    if isinstance(q, dict):
        return q.get("value"), q.get("unit") or q.get("code")
    for f in ("valueString", "valueBoolean", "valueInteger", "valueDateTime"):
        if f in rj:
            return rj[f], None
    cc = rj.get("valueCodeableConcept")
    if cc:
        return _concept(cc)[0], None
    return None, None


def narrative_text(rj: dict) -> str | None:
    """The euIPS narrative as PLAIN TEXT.

    Every resource carries an XHTML `text.div`, which the euIPS guideline
    calls the safety net — "this is what a clinician abroad sees". Returned
    with the markup stripped, because a consumer that rendered the div as HTML
    would be rendering markup it did not write.
    """
    div = (rj.get("text") or {}).get("div")
    if not isinstance(div, str):
        return None
    out = _WS.sub(" ", _TAG.sub(" ", div)).strip()
    return out or None


def entry(row) -> dict:
    rj = row.resource_json if isinstance(row.resource_json, dict) else {}
    rtype = euips.canonical_resource_type(row.resource_type)
    display = code = system = None
    for f in _CONCEPT_FIELDS.get(row.resource_type, ()) + _CONCEPT_FIELDS.get(rtype, ()):
        display, code, system = _concept(rj.get(f))
        if display or code:
            break
    value, unit = _value(rj)
    return {
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "display": display,
        "code": code,
        # Stated per entry, because the platform has TWO diagnosis registers
        # in two code systems (#984): ips codes problems in SNOMED CT, icd11 in
        # ICD-11 MMS. A consumer must be able to label the source, not guess.
        "system": system,
        "date": _date(rj),
        "status": _status(rj),
        "value": value,
        "unit": unit,
        "narrative_text": narrative_text(rj),
        "source": "ips",
    }


def compose(rows) -> list[dict]:
    """Every section, in catalogue order, with its status and its entries.

    A section's entries are the rows `section_matches` assigns to it, EXCEPT
    absent assertions, which are returned separately under `absent`. When a
    section holds both, its status is PRESENT and the stale assertion is not
    shown — the same rule `status_for_resources` applies.
    """
    rows = list(rows)
    status = euips.status_for_resources(rows)
    out: list[dict] = []
    for s in euips.SECTIONS:
        entries, absent = [], None
        for r in rows:
            rj = r.resource_json if isinstance(r.resource_json, dict) else {}
            if euips.is_absent_assertion(rj):
                if euips.absent_section_key(rj) == s.key and absent is None:
                    absent = {"code": (_concept(rj.get("code"))[1]),
                              "narrative_text": narrative_text(rj)}
                continue
            if euips.section_matches(s, r.resource_type, rj):
                entries.append(entry(r))
        st = status[s.key]
        out.append({
            "key": s.key,
            "title": s.title,
            "loinc": s.loinc,
            "obligation": s.obligation,
            "obligation_eps": s.obligation_eps,
            "status": st,
            "entries": entries if st == euips.PRESENT else [],
            "absent": absent if st == euips.EXPLICITLY_ABSENT else None,
        })
    return out
