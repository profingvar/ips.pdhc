"""#795 — the seven euIPS OPTIONAL sections.

Vital signs; past illnesses; pregnancy (current and history); social history;
functional status; plan of care; advance directives.

Optional means plain absence is correct, so each section is generated for a
realistic subset. A cohort in which every patient has an advance directive is
less useful for testing than one where some do.

## Three places this could produce nonsense, and what is done about each

**1. Pregnancy, and the nuance the ticket's warning hides.** The ticket says a
pregnancy on a male or an 80-year-old is generated nonsense. True for CURRENT
pregnancy — but pregnancy *history* is perfectly valid for an 80-year-old
woman, who may well have had children. Banning all pregnancy data above 50
would be its own error. So the two are separated:

* current pregnancy status: female, age 15-50
* pregnancy history (gravida/para): female, age 20 and over, no upper bound

Never for a male or unknown-sex patient, in either form.

**2. Past illnesses versus the active problem list.** They share `Condition`
and are told apart ONLY by `clinicalStatus`. Everything here is resolved or
inactive; #793 emits only active. The discriminators in `euips_sections`
enforce the split on the reading side too — before that, a resolved condition
made `problems` read PRESENT and a patient with an empty active problem list
was called conformant.

**3. Advance directives are not care consent.** A FHIR `Consent` resource in
`fhir_resources`, deliberately NOT a `patient_consents` row: that table is
cohesive-care consent under Lag 2022:913 §5 and is read by `/consents/check`,
which request.pdhc and contract.pdhc both call. Verified before writing this:
`consents_routes.py` never touches `fhir_resources`, so the two are
structurally isolated and an advance directive cannot be mistaken for
permission to share data.

## Observation categories carry the section

Seven sections map to `Observation`. They are distinguished by
`category` — `vital-signs`, `social-history`, `survey` — so every Observation
here MUST carry one, or it will not be attributed to its section at all.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from app.services import euips_sections as euips

#: Probability each optional section is present for a given patient.
PRESENCE_RATE = {
    "vital_signs": 0.90,          # the commonest thing in any record
    "past_illnesses": 0.45,
    "pregnancy": 0.35,            # of ELIGIBLE patients only -- see below
    "social_history": 0.60,
    "functional_status": 0.25,
    "plan_of_care": 0.30,
    "advance_directives": 0.15,   # genuinely uncommon
}

_VITALS = [
    ("8867-4", "Heart rate", "/min", 55, 95),
    ("8480-6", "Systolic blood pressure", "mm[Hg]", 105, 160),
    ("8462-4", "Diastolic blood pressure", "mm[Hg]", 60, 95),
    ("8310-5", "Body temperature", "Cel", 36.0, 37.5),
    ("29463-7", "Body weight", "kg", 55, 110),
    ("8302-2", "Body height", "cm", 155, 195),
    ("9279-1", "Respiratory rate", "/min", 12, 20),
    ("2708-6", "Oxygen saturation", "%", 94, 99),
]

_PAST_ILLNESSES = [
    ("40055000", "Chronic sinusitis", 5),
    ("233604007", "Pneumonia", 10),
    ("1734006", "Fracture of radius", 8),
    ("80146002", "Appendicitis", 10),
    ("36971009", "Sinusitis", 5),
    ("230690007", "Cerebrovascular accident", 55),
]

#: Smoking and alcohol, per the ticket. LOINC with SNOMED answers.
_SOCIAL_HISTORY = [
    ("72166-2", "Tobacco smoking status", [
        ("266919005", "Never smoked tobacco"),
        ("8517006", "Ex-smoker"),
        ("77176002", "Smoker"),
    ]),
    ("74013-4", "Alcoholic drinks per day", [
        ("105542008", "Non-drinker"),
        ("219006", "Current drinker of alcohol"),
    ]),
]

_FUNCTIONAL = [
    ("45605-3", "Independent in activities of daily living"),
    ("46610-1", "Requires assistance with mobility"),
    ("72133-2", "Uses a walking aid"),
]

_CARE_PLAN_TITLES = [
    ("Hypertension follow-up", "Blood pressure review every 3 months."),
    ("Diabetes care plan", "HbA1c every 6 months, annual retinal screening."),
    ("Asthma action plan", "Peak-flow diary; review inhaler technique."),
    ("Post-operative rehabilitation", "Physiotherapy twice weekly for 8 weeks."),
]

#: Advance directives. SNOMED-coded intents, deliberately phrased as the
#: patient's own decision rather than a clinical order.
_ADVANCE_DIRECTIVES = [
    ("61420007", "Do not attempt resuscitation",
     "Patient has recorded a decision against attempted resuscitation."),
    ("225204009", "Organ donation consent",
     "Patient consents to organ donation."),
    ("713673000", "Advance statement of treatment preferences",
     "Patient has recorded treatment preferences for future incapacity."),
]

#: Pregnancy. Current status is age-bounded; history is not, because an
#: 80-year-old woman may well have had children.
CURRENT_PREGNANCY_AGE = (15, 50)
PREGNANCY_HISTORY_MIN_AGE = 20


def _narrative(text: str) -> dict:
    return {"status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{escape(text)}</div>'}


def _cc(system: str, code: str, display: str) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}],
            "text": display}


def _category(code: str, display: str) -> list:
    return [_cc("http://terminology.hl7.org/CodeSystem/observation-category",
                code, display)]


def _parse_birth(birth) -> date | None:
    if isinstance(birth, date):
        return birth
    if isinstance(birth, str) and len(birth) >= 10:
        try:
            return date(int(birth[0:4]), int(birth[5:7]), int(birth[8:10]))
        except ValueError:
            return None
    return None


def _age(birth: date | None) -> int:
    if birth is None:
        return 40
    t = date.today()
    return max(0, t.year - birth.year - ((t.month, t.day) < (birth.month, birth.day)))


def _recent(rng: random.Random, days: int = 365) -> str:
    d = date.today() - timedelta(days=rng.randint(1, days))
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


def _at_age(birth: date | None, years: float, rng: random.Random) -> str:
    if birth is None:
        return _recent(rng)
    d = birth + timedelta(days=int(years * 365.25) + rng.randint(0, 200))
    today = date.today()
    if d > today:
        d = today - timedelta(days=rng.randint(1, 365))
    if d < birth:
        d = birth + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


# ----------------------------------------------------------------- vital signs

def _vital_signs(ref: str, birth, rng: random.Random) -> list[dict]:
    out = []
    for code, display, unit, lo, hi in rng.sample(_VITALS, rng.randint(3, 6)):
        val = round(rng.uniform(lo, hi), 1)
        out.append({
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display}: {val} {unit}."),
            "subject": {"reference": ref},
            "status": "final",
            # REQUIRED for attribution: seven sections map to Observation and
            # the category is what separates them.
            "category": _category("vital-signs", "Vital Signs"),
            "code": _cc("http://loinc.org", code, display),
            "valueQuantity": {"value": val, "unit": unit,
                              "system": "http://unitsofmeasure.org",
                              "code": unit},
            "effectiveDateTime": _recent(rng, 180),
        })
    return out


# -------------------------------------------------------------- past illnesses

def _past_illnesses(ref: str, birth, rng: random.Random) -> list[dict]:
    age = _age(_parse_birth(birth))
    eligible = [p for p in _PAST_ILLNESSES if age >= p[2] + 2]
    if not eligible:
        return []
    out = []
    for code, display, min_age in rng.sample(
            eligible, min(len(eligible), rng.randint(1, 2))):
        out.append({
            "resourceType": "Condition",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display}, resolved."),
            "subject": {"reference": ref},
            # RESOLVED. #793 emits only active, and the two sections are told
            # apart by nothing else.
            "clinicalStatus": _cc(
                "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "resolved", "Resolved"),
            "code": _cc("http://snomed.info/sct", code, display),
            "onsetDateTime": _at_age(_parse_birth(birth),
                                     rng.uniform(min_age, max(min_age + 1, age - 1)),
                                     rng),
        })
    return out


# ------------------------------------------------------------------- pregnancy

def pregnancy_eligibility(gender: str | None, age: int) -> tuple[bool, bool]:
    """(may_have_current_pregnancy, may_have_pregnancy_history).

    Separated on purpose. A current pregnancy outside 15-50, or on a male
    patient, is nonsense a clinician notices at once. But pregnancy HISTORY is
    valid for an 80-year-old woman, and refusing it would be a different error
    — the ticket's warning, taken literally, would have produced it.
    """
    if (gender or "").lower() != "female":
        return False, False
    lo, hi = CURRENT_PREGNANCY_AGE
    return (lo <= age <= hi), (age >= PREGNANCY_HISTORY_MIN_AGE)


def _pregnancy(ref: str, birth, gender, rng: random.Random) -> list[dict]:
    age = _age(_parse_birth(birth))
    may_current, may_history = pregnancy_eligibility(gender, age)
    out = []
    if may_history and rng.random() < 0.7:
        n = rng.randint(1, 4)
        out.append({
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"Number of pregnancies: {n}."),
            "subject": {"reference": ref},
            "status": "final",
            "category": _category("social-history", "Social History"),
            "code": _cc("http://loinc.org", "11640-0", "Number of pregnancies"),
            "valueQuantity": {"value": n, "unit": "1",
                              "system": "http://unitsofmeasure.org", "code": "1"},
            "effectiveDateTime": _recent(rng, 1000),
        })
    if may_current and rng.random() < 0.15:
        out.append({
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "text": _narrative("Currently pregnant."),
            "subject": {"reference": ref},
            "status": "final",
            "category": _category("social-history", "Social History"),
            "code": _cc("http://loinc.org", "82810-3", "Pregnancy status"),
            "valueCodeableConcept": _cc("http://snomed.info/sct", "77386006",
                                        "Pregnant"),
            "effectiveDateTime": _recent(rng, 180),
        })
    return out


# -------------------------------------------------------------- social history

def _social_history(ref: str, birth, rng: random.Random) -> list[dict]:
    age = _age(_parse_birth(birth))
    if age < 13:
        return []            # smoking and alcohol status on a child is nonsense
    out = []
    for code, display, answers in _SOCIAL_HISTORY:
        acode, adisplay = rng.choice(answers)
        out.append({
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display}: {adisplay}."),
            "subject": {"reference": ref},
            "status": "final",
            "category": _category("social-history", "Social History"),
            "code": _cc("http://loinc.org", code, display),
            "valueCodeableConcept": _cc("http://snomed.info/sct", acode, adisplay),
            "effectiveDateTime": _recent(rng, 365),
        })
    return out


# ----------------------------------------------------------- functional status

def _functional_status(ref: str, birth, rng: random.Random) -> list[dict]:
    code, display = rng.choice(_FUNCTIONAL)
    return [{
        "resourceType": "Observation",
        "id": str(uuid.uuid4()),
        "text": _narrative(f"{display}."),
        "subject": {"reference": ref},
        "status": "final",
        # `survey` is the closest standard observation-category; HL7 defines no
        # `functional-status` code. Recorded in euips_sections rather than
        # invented.
        "category": _category("survey", "Survey"),
        "code": _cc("http://loinc.org", code, display),
        "effectiveDateTime": _recent(rng, 365),
    }]


# ----------------------------------------------------------------- plan of care

def _plan_of_care(ref: str, birth, rng: random.Random) -> list[dict]:
    title, detail = rng.choice(_CARE_PLAN_TITLES)
    return [{
        "resourceType": "CarePlan",
        "id": str(uuid.uuid4()),
        "text": _narrative(f"{title}: {detail}"),
        "subject": {"reference": ref},
        "status": "active",
        "intent": "plan",
        "title": title,
        "description": detail,
        "period": {"start": _recent(rng, 365)},
    }]


# ----------------------------------------------------------- advance directives

def _advance_directives(ref: str, birth, rng: random.Random) -> list[dict]:
    """A FHIR Consent in fhir_resources — NOT a patient_consents row.

    patient_consents is cohesive-care consent (Lag 2022:913 §5) read by
    /consents/check, which request.pdhc and contract.pdhc call. An advance
    directive is a different thing and must not be mistakable for permission
    to share data. Verified: consents_routes.py never reads fhir_resources.
    """
    age = _age(_parse_birth(birth))
    if age < 18:
        return []            # a minor does not record their own directive here
    code, display, note = rng.choice(_ADVANCE_DIRECTIVES)
    return [{
        "resourceType": "Consent",
        "id": str(uuid.uuid4()),
        "text": _narrative(note),
        "patient": {"reference": ref},
        "status": "active",
        # `acd` = advance care directive, the HL7 consent-scope code. This is
        # what keeps it readable as a directive rather than a data-sharing
        # permission.
        "scope": _cc("http://terminology.hl7.org/CodeSystem/consentscope",
                     "adr", "Advance Care Directive"),
        "category": [_cc("http://snomed.info/sct", code, display)],
        "dateTime": _recent(rng, 1500),
    }]


_BUILDERS = {
    "vital_signs": _vital_signs,
    "past_illnesses": _past_illnesses,
    "social_history": _social_history,
    "functional_status": _functional_status,
    "plan_of_care": _plan_of_care,
    "advance_directives": _advance_directives,
}


def optional_sections_for(patient_ref: str, birth=None, gender: str | None = None,
                          *, rng: random.Random | None = None) -> list[dict]:
    """The optional sections for one patient.

    No absent assertions here: IPS defines none for these sections, and the
    plan forbids inventing codes. So each section is content or nothing, and
    nothing is correct.
    """
    r = rng or random
    out: list[dict] = []
    for key, builder in _BUILDERS.items():
        if r.random() < PRESENCE_RATE[key]:
            out.extend(builder(patient_ref, birth, r))
    if r.random() < PRESENCE_RATE["pregnancy"]:
        out.extend(_pregnancy(patient_ref, birth, gender, r))
    return out
