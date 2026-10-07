"""#793 — the three euIPS REQUIRED sections, which may never be empty.

The guideline: *"Where the coding is incomplete, the absent / unknown codes
still have to be given explicitly. This applies, for example, to the required
sections: you must state 'no known allergies' rather than leave the section
empty."*

Measured in production 2026-10-07, by the shipped #791 code: of 150 patients,
**40 were conformant and 110 had no content in ANY section** — not "no known
allergies", no statement whatsoever. 110 of 150 summaries invalid on this rule
alone.

So this module builds, for every generated patient, one of two things per
required section:

* a real coded entry, or
* an explicit absent assertion carrying the IPS `absent-unknown-uv-ips` code.

Never nothing. There is no flag that turns it off — a switch that produces an
invalid summary is a trap, and `skip_clinical` is handled by emitting the
absent assertions rather than by skipping the sections (see
`required_sections_for`).

## Narrative as well as codes

euIPS is explicitly a hybrid format, and the guideline calls the narrative the
safety net: *"Every section carries human-readable text. This is what a
clinician abroad sees."* So every resource here carries `text` with a
`status` and an XHTML `div`. A coded-only entry would satisfy a FHIR validator
and still fail the thing the section is for.

## Active versus past

`problems` is the ACTIVE problem list. Past illnesses are a separate, OPTIONAL
section (#795), and the two are told apart ONLY by `clinicalStatus` — so
everything built here is `active`, and a resolved condition must never be
emitted by this module.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from app.services import euips_sections as euips

#: How often a patient genuinely has nothing to report in each required
#: section, so BOTH paths are exercised by any reasonable batch size.
#:
#: Deliberately simple numbers, not an epidemiological model: the existing
#: generator already records that "sim.pdhc owns the data semantics" and this
#: only needs a valid summary to attach data to. "No known allergies" being the
#: commonest of the three matches ordinary clinical reality and makes the
#: absent path the normal case rather than an edge case nobody sees.
ABSENT_RATE = {
    "allergies": 0.55,
    "problems": 0.15,
    "medications": 0.25,
}

_ALLERGIES = [
    ("91936005", "Allergy to penicillin"),
    ("293585002", "Allergy to acetylsalicylic acid"),
    ("232347008", "Allergy to peanut"),
    ("425525006", "Allergy to lactose"),
    ("300916003", "Allergy to latex"),
    ("419263009", "Allergy to pollen"),
]

_CONDITIONS = [
    ("38341003", "Hypertension"),
    ("44054006", "Type 2 diabetes mellitus"),
    ("195967001", "Asthma"),
    ("13645005", "Chronic obstructive pulmonary disease"),
    ("84114007", "Heart failure"),
    ("49436004", "Atrial fibrillation"),
    ("396275006", "Osteoarthritis"),
    ("35489007", "Depressive disorder"),
]

_MEDICATIONS = [
    ("C09AA05", "Ramipril"),
    ("A10BA02", "Metformin"),
    ("R03AC02", "Salbutamol"),
    ("C07AB07", "Bisoprolol"),
    ("B01AC06", "Acetylsalicylic acid"),
    ("C10AA05", "Atorvastatin"),
    ("A02BC01", "Omeprazole"),
]


def _narrative(text: str) -> dict:
    """A FHIR Narrative. `generated` because a simulator produced it, and the
    text is escaped because a display string ends up inside XHTML."""
    return {"status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{escape(text)}</div>'}


def _cc(system: str, code: str, display: str) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}],
            "text": display}


def _allergy(patient_ref: str, now: str, rng: random.Random) -> dict:
    code, display = rng.choice(_ALLERGIES)
    return {
        "resourceType": "AllergyIntolerance",
        "id": str(uuid.uuid4()),
        "text": _narrative(f"{display}. Reaction recorded."),
        "patient": {"reference": patient_ref},
        "clinicalStatus": _cc(
            "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
            "active", "Active"),
        "verificationStatus": _cc(
            "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
            "confirmed", "Confirmed"),
        "category": ["medication"],
        "criticality": rng.choice(["low", "high"]),
        "code": _cc("http://snomed.info/sct", code, display),
        "recordedDate": now,
    }


def _no_known_allergies(patient_ref: str, now: str) -> dict:
    """The guideline's own example of the rule."""
    return {
        "resourceType": "AllergyIntolerance",
        "id": str(uuid.uuid4()),
        "text": _narrative("No known allergies."),
        "patient": {"reference": patient_ref},
        "clinicalStatus": _cc(
            "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
            "active", "Active"),
        "code": euips.absent_coding("allergies"),
        "recordedDate": now,
    }


def _condition(patient_ref: str, now: str, rng: random.Random) -> dict:
    code, display = rng.choice(_CONDITIONS)
    return {
        "resourceType": "Condition",
        "id": str(uuid.uuid4()),
        "text": _narrative(f"{display}, active."),
        "subject": {"reference": patient_ref},
        # ACTIVE. Past illnesses are a different section (#795) and the only
        # thing separating them is this field.
        "clinicalStatus": _cc(
            "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "active", "Active"),
        "verificationStatus": _cc(
            "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            "confirmed", "Confirmed"),
        "code": _cc("http://snomed.info/sct", code, display),
        "recordedDate": now,
    }


def _no_known_problems(patient_ref: str, now: str) -> dict:
    return {
        "resourceType": "Condition",
        "id": str(uuid.uuid4()),
        "text": _narrative("No known problems."),
        "subject": {"reference": patient_ref},
        "clinicalStatus": _cc(
            "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "active", "Active"),
        "code": euips.absent_coding("problems"),
        "recordedDate": now,
    }


def _medication(patient_ref: str, now: str, rng: random.Random) -> dict:
    code, display = rng.choice(_MEDICATIONS)
    return {
        "resourceType": "MedicationStatement",
        "id": str(uuid.uuid4()),
        "text": _narrative(f"{display}, ongoing."),
        "subject": {"reference": patient_ref},
        "status": "active",
        # `medication`, which is what this codebase writes and what all 119
        # pre-existing rows use. euips_sections._CODE_BEARING_FIELDS has to
        # agree with this or an absent assertion here is undetectable.
        "medication": _cc("http://www.whocc.no/atc", code, display),
        "dateAsserted": now,
    }


def _no_known_medications(patient_ref: str, now: str) -> dict:
    return {
        "resourceType": "MedicationStatement",
        "id": str(uuid.uuid4()),
        "text": _narrative("No known medications."),
        "subject": {"reference": patient_ref},
        "status": "unknown",
        "medication": euips.absent_coding("medications"),
        "dateAsserted": now,
    }


def required_sections_for(patient_ref: str, *, rng: random.Random | None = None,
                          absent_only: bool = False) -> list[dict]:
    """All three required sections for one patient. Never returns fewer.

    `absent_only=True` is the `skip_clinical` path: it emits the three absent
    assertions and nothing else. That is the decision #793 asked for, and the
    reason is that the alternative — skipping the sections — produces a
    non-conformant patient. `skip_clinical` exists so sim.pdhc can own the
    clinical data without two sources of truth, which is a good reason; it is
    not a reason to emit an invalid summary in the meantime. sim overwrites
    real content later, and `status_for_resources` prefers real content over a
    stale absent assertion precisely so that works.
    """
    r = rng or random
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []

    if absent_only or r.random() < ABSENT_RATE["allergies"]:
        out.append(_no_known_allergies(patient_ref, now))
    else:
        for _ in range(r.randint(1, 2)):
            out.append(_allergy(patient_ref, now, r))

    if absent_only or r.random() < ABSENT_RATE["problems"]:
        out.append(_no_known_problems(patient_ref, now))
    else:
        for _ in range(r.randint(1, 3)):
            out.append(_condition(patient_ref, now, r))

    if absent_only or r.random() < ABSENT_RATE["medications"]:
        out.append(_no_known_medications(patient_ref, now))
    else:
        for _ in range(r.randint(1, 3)):
            out.append(_medication(patient_ref, now, r))

    return out
