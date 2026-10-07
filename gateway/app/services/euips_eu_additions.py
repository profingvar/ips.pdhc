"""#796 — the three EU-specific euIPS sections.

Medical alerts; travel history; patient-provided information. The eHealth
Network guideline and the Xt-EHR EHDS logical models add these beyond the base
IPS, listing them as separate building blocks.

## Medical alerts, and why provenance is marked

Measured before writing this: **no `Flag` resource exists anywhere on the
platform.** Zero rows in ips, and nothing in request.pdhc, cdr.pdhc or
gateway.pdhc emits one. So these are the platform's FIRST Flags, which means
the simulator is establishing the convention.

That matters because of the MDR boundary. plan.pdhc authors thresholds (out of
scope); **request.pdhc applies them and alerts (in scope, likely Rule 11)**. If
that path later emits computed alerts as Flags and the simulated ones carry no
provenance, the ambiguity is created retroactively and the evidence for a
technical file is polluted by test data that looks clinical.

So every Flag here carries `meta.tag` with
`urn:pdhc:provenance#simulated`, says so in its narrative, and names the
simulator as author. A computed alert must never be mistakable for a generated
one, and establishing that now costs nothing.

## Travel history: the code is provisional and labelled

#795 deliberately left `euips_sections.TRAVEL_CODES` empty, because no code is
established for this EU addition and a guessed one would make the section claim
observations that are not travel history. This ticket has to settle something,
so it uses SNOMED `420008001` ("Travel") — **provisional**, consistent with
`CODES_VERIFIED = False`, and recorded here as the single place to change when
the terminology is verified. The section reads MISSING until then only because
nothing generated it; now it reads PRESENT off a code that is explicitly marked
unverified rather than quietly asserted.

Dates relate to a plausible recent window rather than floating free, because
travel history exists for infectious-disease reasoning and a date that
precedes the relevant illness is the only kind that carries information.

## Patient-provided information

Distinguished by the resource's own source, not by a separate type:
`performer` references the subject. That distinction IS the section — what the
patient asserted carries different weight from what a clinician recorded, and
unmarked the section is decorative. `euips_sections._is_patient_asserted`
reads exactly this.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from app.services import euips_sections as euips

PRESENCE_RATE = {
    "alerts": 0.20,              # an alert should be uncommon, or it is noise
    "travel_history": 0.25,
    "patient_provided": 0.35,
}

#: The provenance tag that keeps a SIMULATED alert distinguishable from a
#: COMPUTED one. See the module docstring: the computed path is the
#: MDR-relevant surface, so this must never be silently droppable.
PROVENANCE_SYSTEM = "urn:pdhc:provenance"
SIMULATED = "simulated"

#: Clinically weighty alerts — the section exists so a clinician abroad sees
#: these first.
_ALERTS = [
    ("1023001", "Anticoagulant therapy — bleeding risk",
     "Patient is on long-term anticoagulation."),
    ("419099009", "Risk of anaphylaxis",
     "Previous anaphylactic reaction recorded."),
    ("161477002", "Difficult airway",
     "Intubation previously documented as difficult."),
    ("58597006", "Implanted device present — MRI caution",
     "Implanted device; confirm MRI compatibility before imaging."),
]

#: Travel destinations with a reason the history matters.
_TRAVEL = [
    ("Thailand", "Dengue and malaria risk area."),
    ("Kenya", "Malaria and yellow-fever risk area."),
    ("Brazil", "Dengue, Zika and yellow-fever risk area."),
    ("India", "Typhoid and hepatitis A risk area."),
    ("Spain", "No specific infectious risk recorded."),
]

#: What a patient reports themselves, as opposed to a clinician's record.
_PATIENT_REPORTED = [
    ("75321-0", "Clinical finding reported by patient",
     "Patient reports intermittent dizziness on standing."),
    ("72514-3", "Pain severity, patient-reported",
     "Patient reports pain 4 of 10 in the lower back."),
    ("89204-2", "Patient-reported sleep quality",
     "Patient reports poor sleep for several weeks."),
]


def _narrative(text: str) -> dict:
    return {"status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{escape(text)}</div>'}


def _cc(system: str, code: str, display: str) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}],
            "text": display}


def simulated_meta() -> dict:
    """`meta.tag` marking this resource as simulator output.

    A separate function because it must be applied uniformly and is the thing
    a test asserts on every generated alert.
    """
    return {"tag": [{"system": PROVENANCE_SYSTEM, "code": SIMULATED,
                     "display": "Generated by the ips.pdhc patient simulator"}]}


def is_simulated(resource_json: dict | None) -> bool:
    """True when this resource carries the simulated-provenance tag.

    The read side of the MDR distinction: a consumer that must separate test
    data from clinical content asks this rather than guessing from content.
    """
    if not isinstance(resource_json, dict):
        return False
    for tag in (resource_json.get("meta") or {}).get("tag") or []:
        if isinstance(tag, dict) and tag.get("system") == PROVENANCE_SYSTEM \
                and tag.get("code") == SIMULATED:
            return True
    return False


def _recent(rng: random.Random, days: int = 540) -> str:
    d = date.today() - timedelta(days=rng.randint(14, days))
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


def _alerts(ref: str, rng: random.Random) -> list[dict]:
    code, display, note = rng.choice(_ALERTS)
    return [{
        "resourceType": "Flag",
        "id": str(uuid.uuid4()),
        # Marked at the resource level, so it survives being read out of
        # context -- in a bundle, a search result or an export.
        "meta": simulated_meta(),
        "text": _narrative(f"SIMULATED ALERT — {note} "
                           f"(generated test data, not a computed alert)"),
        "status": "active",
        "category": [_cc("http://terminology.hl7.org/CodeSystem/flag-category",
                         "clinical", "Clinical")],
        "code": _cc("http://snomed.info/sct", code, display),
        "subject": {"reference": ref},
        "period": {"start": _recent(rng, 365)},
        # Named author, so provenance is legible without reading meta.
        "author": {"display": "ips.pdhc patient simulator"},
    }]


def _travel_history(ref: str, rng: random.Random) -> list[dict]:
    place, why = rng.choice(_TRAVEL)
    when = _recent(rng, 900)
    returned = (date.fromisoformat(when[:10])
                + timedelta(days=rng.randint(7, 28)))
    code = next(iter(euips.TRAVEL_CODES))
    return [{
        "resourceType": "Observation",
        "id": str(uuid.uuid4()),
        "meta": simulated_meta(),
        "text": _narrative(f"Travel to {place}, returned "
                           f"{returned.isoformat()}. {why}"),
        "subject": {"reference": ref},
        "status": "final",
        "category": [_cc(
            "http://terminology.hl7.org/CodeSystem/observation-category",
            "social-history", "Social History")],
        "code": _cc("http://snomed.info/sct", code, "Travel"),
        "valueString": place,
        # A period, not an instant: "when did you travel" is a window, and the
        # window is what relates it to an illness.
        "effectivePeriod": {"start": when,
                            "end": datetime(returned.year, returned.month,
                                            returned.day,
                                            tzinfo=timezone.utc).isoformat()},
    }]


def _patient_provided(ref: str, rng: random.Random) -> list[dict]:
    code, display, note = rng.choice(_PATIENT_REPORTED)
    return [{
        "resourceType": "Observation",
        "id": str(uuid.uuid4()),
        "meta": simulated_meta(),
        "text": _narrative(f"Patient-reported: {note}"),
        "subject": {"reference": ref},
        "status": "final",
        "category": [_cc(
            "http://terminology.hl7.org/CodeSystem/observation-category",
            "survey", "Survey")],
        "code": _cc("http://loinc.org", code, display),
        # THE discriminator: the performer IS the subject. Without this the
        # resource is an ordinary clinician-recorded observation and the
        # section means nothing.
        "performer": [{"reference": ref}],
        "valueString": note,
        "effectiveDateTime": _recent(rng, 180),
    }]


_BUILDERS = {
    "alerts": _alerts,
    "travel_history": _travel_history,
    "patient_provided": _patient_provided,
}


def eu_addition_sections_for(patient_ref: str,
                             *, rng: random.Random | None = None) -> list[dict]:
    """The three EU-addition sections for one patient.

    No absent assertions: IPS defines no absent code for any of these, so each
    section is content or nothing, and nothing is correct.
    """
    r = rng or random
    out: list[dict] = []
    for key, builder in _BUILDERS.items():
        if r.random() < PRESENCE_RATE[key]:
            out.extend(builder(patient_ref, r))
    return out
