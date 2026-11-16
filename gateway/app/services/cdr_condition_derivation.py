"""#984 — the EPS problems section is DERIVED from the CDR.

Operator decision 2026-11-16: diagnoses are recorded in the CDR; the EPS is a
summary of it. This module takes the CDR's Conditions (an export of the
`condition` table, one row per CDR Condition) and makes the EPS agree:

- a CDR Condition that came FROM the EPS (#984 backfill: it carries the ips
  identifier) gets a NEW VERSION of its ips Condition carrying the CDR link;
- a CDR Condition with no EPS twin (icd11's, for instance) is CREATED in the
  EPS, linked the same way, with a stable id so a re-run finds it;
- nothing is deleted. An EPS Condition with no CDR row stays, and is visible
  as such by having no link (`is_cdr_backed`).

Every write is a new version (#934). Re-running on the same export changes
nothing.
"""
from __future__ import annotations

import copy
import uuid

IPS_IDENTIFIER_SYSTEM = "https://ips.pdhc.se/fhir/Condition"
CDR_IDENTIFIER_SYSTEM = "https://cdr.pdhc.se/fhir/Condition"
DERIVED_TAG = {"system": "https://ips.pdhc.se/CodeSystem/provenance",
               "code": "derived-from-cdr", "display": "Derived from the CDR (#984)"}
_NS = uuid.UUID("9e4c1f0a-0984-4d84-b984-c0d1e1d1e984")
#: Copied from the CDR row onto a NEW EPS Condition. Not meta, not text, not
#: the CDR's own security labels: those describe the CDR's copy.
_COPY = ("code", "clinicalStatus", "verificationStatus", "category", "severity",
         "onsetDateTime", "onsetPeriod", "abatementDateTime", "recordedDate", "note", "bodySite")


def eps_id_for(cdr_guid: str) -> str:
    return str(uuid.uuid5(_NS, f"cdr/Condition/{cdr_guid}"))


def _ident(resource: dict, system: str) -> str | None:
    for i in resource.get("identifier") or []:
        if i.get("system") == system and i.get("value"):
            return i["value"]
    return None


def is_cdr_backed(resource: dict) -> bool:
    return _ident(resource, CDR_IDENTIFIER_SYSTEM) is not None


def link(resource: dict, cdr_guid: str, cdr_name: str) -> dict:
    """`resource` with the CDR link added (a copy). Idempotent."""
    out = copy.deepcopy(resource)
    if _ident(out, CDR_IDENTIFIER_SYSTEM) == cdr_guid:
        return out
    ids = [i for i in out.get("identifier") or [] if i.get("system") != CDR_IDENTIFIER_SYSTEM]
    ids.append({"system": CDR_IDENTIFIER_SYSTEM, "value": cdr_guid,
                "assigner": {"display": cdr_name}})
    out["identifier"] = ids
    meta = out.setdefault("meta", {})
    tags = [t for t in meta.get("tag") or [] if t.get("code") != DERIVED_TAG["code"]]
    meta["tag"] = tags + [dict(DERIVED_TAG)]
    return out


def new_eps_condition(cdr_row: dict) -> dict:
    raw = cdr_row["raw_json"]
    out = {"resourceType": "Condition", "id": eps_id_for(cdr_row["guid"]),
           "subject": {"reference": f"Patient/{cdr_row['patient_guid']}"}}
    for k in _COPY:
        if k in raw:
            out[k] = copy.deepcopy(raw[k])
    return link(out, cdr_row["guid"], cdr_row["cdr"])


def plan(cdr_rows: list[dict], current: dict[str, dict]) -> list[tuple]:
    """The changes, as (action, resource_id, patient_guid, new_json).

    `current` maps ips Condition resource_id -> its active resource_json.
    action is "link" (new version of an existing EPS Condition) or
    "create" (a CDR Condition with no EPS twin). Raises ValueError on a CDR
    row that names an ips Condition the EPS does not have: that is a
    broken link, and writing around it would hide it.
    """
    out = []
    for row in cdr_rows:
        raw = row["raw_json"]
        ips_id = _ident(raw, IPS_IDENTIFIER_SYSTEM)
        if ips_id is not None:
            if ips_id not in current:
                raise ValueError(f"CDR {row['cdr']} Condition {row['guid']} names ips "
                                 f"Condition {ips_id}, which the EPS does not have")
            new = link(current[ips_id], row["guid"], row["cdr"])
            if new != current[ips_id]:
                out.append(("link", ips_id, row["patient_guid"], new))
            continue
        eid = eps_id_for(row["guid"])
        if eid in current:
            continue    # already derived; the CDR row is the record, not re-copied here
        out.append(("create", eid, row["patient_guid"], new_eps_condition(row)))
    return out
