"""#934 — bring stored MedicationStatement / Procedure rows to R5 element names.

#1010 fixed what this service WRITES (MedicationStatement `status: recorded`,
`medication: {concept: ...}`). The rows written before it still carry the old
shapes — measured in production 2026-11-16:

    MedicationStatement  322 rows: `medication` a bare CodeableConcept
                         ({text, coding}), status `active` (268) / `unknown` (54)
    Procedure             18 rows: `performedDateTime` (R4); R5 is `occurrence[x]`

Every change is written as a NEW VERSION (#934's decision), so the R4 content
survives as `superseded` — which is why the status mapping may be coarse
without losing anything: the original value is still in v1.

The mapping is exactly what the writers produce since #1010, nothing invented:

  MedicationStatement
    status            `entered-in-error` and `draft` kept; every other R4 value
                      -> `recorded` (R5's valueset is recorded | entered-in-
                      error | draft). The "no known medications" rows carry
                      their absence in the CODE (absent_coding), not in status,
                      so `unknown` -> `recorded` does not change the section.
    medication        bare CodeableConcept -> {"concept": <it>}
    medicationCodeableConcept -> medication.concept
    medicationReference       -> medication.reference
  Procedure
    performed<X> -> occurrence<X> for DateTime/Period/String/Age/Range. Where
    both are present the R5 one wins and the stale one goes.

A pure function, so it is tested on SQLite exactly as it runs on Postgres
(the #908 pattern).
"""
from __future__ import annotations

HANDLED_TYPES = ("MedicationStatement", "Procedure")

R5_MS_STATUS = {"recorded", "entered-in-error", "draft"}
PROC_SUFFIXES = ("DateTime", "Period", "String", "Age", "Range")


def _is_bare_codeable_concept(v) -> bool:
    return (isinstance(v, dict) and "concept" not in v and "reference" not in v
            and ("coding" in v or "text" in v))


def migrate_resource_json(resource_type: str, resource_json):
    """Return ``(new_json, changes)``; ``changes == []`` means the SAME object."""
    if resource_type not in HANDLED_TYPES or not isinstance(resource_json, dict):
        return resource_json, []
    out = dict(resource_json)
    changes: list[str] = []

    if resource_type == "MedicationStatement":
        st = out.get("status")
        if isinstance(st, str) and st not in R5_MS_STATUS:
            out["status"] = "recorded"
            changes.append(f"status:{st}->recorded")
        med = out.get("medication")
        if _is_bare_codeable_concept(med):
            out["medication"] = {"concept": med}
            changes.append("wrap:medication->medication.concept")
        for old, key in (("medicationCodeableConcept", "concept"),
                         ("medicationReference", "reference")):
            if old not in out:
                continue
            val = out.pop(old)
            if isinstance(out.get("medication"), dict) and out["medication"]:
                changes.append(f"drop-stale:{old}")
            else:
                out["medication"] = {key: val}
                changes.append(f"rename:{old}->medication.{key}")

    else:  # Procedure
        for sfx in PROC_SUFFIXES:
            old, new = f"performed{sfx}", f"occurrence{sfx}"
            if old not in out:
                continue
            if any(f"occurrence{s}" in out for s in PROC_SUFFIXES):
                del out[old]
                changes.append(f"drop-stale:{old}")
            else:
                out[new] = out.pop(old)
                changes.append(f"rename:{old}->{new}")

    if not changes:
        return resource_json, []
    return out, changes


def plan(rows) -> dict:
    """Counts per change, rows affected, rows examined — what a run WOULD do."""
    per_change: dict[str, int] = {}
    affected = examined = 0
    for r in rows:
        examined += 1
        _new, changes = migrate_resource_json(r.resource_type, r.resource_json)
        if changes:
            affected += 1
            for c in changes:
                per_change[c] = per_change.get(c, 0) + 1
    return {"examined": examined, "affected": affected, "changes": per_change}
