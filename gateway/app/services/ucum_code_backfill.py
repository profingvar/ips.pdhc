"""Quantities that name UCUM but carry no UCUM code (#870, found in ips).

50 Observations from the 2026-06-03 seed have ``system:
http://unitsofmeasure.org`` with only a free-text ``unit``. Without
``code`` the quantity is not machine-comparable, which is the whole point of
naming UCUM. Two of the texts are not UCUM at all (``mmHg``,
``mL/min/1.73m2``), so the code is MAPPED, never copied blindly.

Same contract as ``r5_clinical_migration``: a pure function, a ``plan``, and
the CLI writes every change as a NEW VERSION. A unit text with no mapping is
left untouched and reported as ``unmapped:<text>``, so the run stops there
rather than guessing.
"""
from __future__ import annotations

import copy

HANDLED_TYPES = ("Observation",)
UCUM = "http://unitsofmeasure.org"

#: Unit text -> UCUM code. Every value is a valid UCUM code
#: (checked against termbank's validator, #870).
TEXT_TO_UCUM = {
    "mmHg": "mm[Hg]",
    "mL/min/1.73m2": "mL/min/{1.73_m2}",
    "%": "%", "kg": "kg", "cm": "cm",
    "umol/L": "umol/L", "mmol/L": "mmol/L",
}


def _quantities(j):
    if isinstance(j.get("valueQuantity"), dict):
        yield "valueQuantity", j["valueQuantity"]
    for i, comp in enumerate(j.get("component") or []):
        if isinstance(comp, dict) and isinstance(comp.get("valueQuantity"), dict):
            yield f"component[{i}]", comp["valueQuantity"]


def migrate_resource_json(rtype, resource_json):
    if rtype not in HANDLED_TYPES or not isinstance(resource_json, dict):
        return resource_json, []
    todo = [(w, q) for w, q in _quantities(resource_json) if q.get("system") == UCUM and not q.get("code")]
    if not todo:
        return resource_json, []
    out = copy.deepcopy(resource_json)
    changes = []
    for where, q in _quantities(out):
        if q.get("system") != UCUM or q.get("code"):
            continue
        code = TEXT_TO_UCUM.get(q.get("unit"))
        if code is None:
            changes.append(f"unmapped:{q.get('unit')}")
            continue
        q["code"] = code
        changes.append(f"code:{q.get('unit')}->{code}")
    if all(c.startswith("unmapped:") for c in changes):
        return resource_json, []  # nothing writable; reported by plan()
    return out, changes


def unmapped(rows) -> dict:
    """Unit texts that would be LEFT without a code."""
    n: dict[str, int] = {}
    for r in rows:
        if r.resource_type not in HANDLED_TYPES or not isinstance(r.resource_json, dict):
            continue
        for _w, q in _quantities(r.resource_json):
            if q.get("system") == UCUM and not q.get("code") and q.get("unit") not in TEXT_TO_UCUM:
                n[q.get("unit")] = n.get(q.get("unit"), 0) + 1
    return n


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
