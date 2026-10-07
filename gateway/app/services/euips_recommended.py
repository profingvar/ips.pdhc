"""#794 — the four euIPS RECOMMENDED sections.

Immunisations; History of procedures; Medical devices and implants; Diagnostic
results (lab and imaging).

## The difference from the required three, made explicit

A required section may never be empty (#793). A **recommended** section
legitimately may. So this module can produce three outcomes per section, and
all three are valid:

| outcome | meaning |
|---|---|
| content | real coded entries |
| explicit absence | the IPS absent/unknown code — "no known immunisations" |
| nothing | no rows at all, which is permitted here and is NOT a defect |

That last row is the whole point of the distinction. #799's validator must not
report a MISSING recommended section as a failure, and a consumer must handle
all three. Generating all three is how that gets exercised instead of assumed.

## What was wrong before

* **Medical devices did not exist.** No `Device` or `DeviceUseStatement`
  resource type was ever written — the live types were Observation, Patient,
  MedicationStatement, Condition, Immunization, AllergyIntolerance,
  DiagnosticReport, Procedure. One of the four recommended sections was simply
  absent from the simulator.
* **Diagnostic reports linked to nothing.** Measured in production: all 61
  rows carry `code`, `status`, `conclusion`, `effectiveDateTime`, `subject` —
  and **no `result`**. A diagnostic-results section whose reports reference no
  observations is a header with a sentence attached, and the results are the
  part a clinician reads.
* **Immunisation dates were generation time.** 97 rows across 40 distinct
  dates, every one the moment its batch ran. So an 80-year-old's childhood
  vaccine was dated today. Dates here are now derived from the patient's birth
  date.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from app.services import euips_sections as euips

#: Probability a section has real content. The remainder splits between an
#: explicit absence and nothing at all -- see ABSENT_SHARE.
PRESENCE_RATE = {
    "immunisations": 0.75,
    "procedures": 0.45,
    "devices": 0.20,
    "diagnostic_results": 0.70,
}

#: Of the patients WITHOUT content, the share that get an explicit "none known"
#: rather than no rows. Both are valid for a recommended section; generating
#: both means downstream code meets both.
ABSENT_SHARE = 0.5

#: Swedish childhood programme, roughly: (ATC, display, age in years at dose).
#: Ages are what make the dates plausible -- the point of this ticket.
_CHILDHOOD_VACCINES = [
    ("J07CA06", "Diphtheria-tetanus-pertussis-polio-Hib", 0.25),
    ("J07CA06", "Diphtheria-tetanus-pertussis-polio-Hib booster", 1.0),
    ("J07BD52", "Measles, mumps and rubella", 1.5),
    ("J07AL02", "Pneumococcal conjugate", 0.5),
    ("J07BM01", "Human papillomavirus", 11.0),
    ("J07AM01", "Tetanus booster", 15.0),
]

#: Given seasonally to older adults, so dated in recent years and gated on age.
_SEASONAL_VACCINES = [
    ("J07BB02", "Influenza vaccine", 60),
    ("J07BX03", "COVID-19 vaccine", 18),
]

_PROCEDURES = [
    ("80146002", "Appendectomy", 15),
    ("397956004", "Coronary angiography", 45),
    ("73761001", "Colonoscopy", 40),
    ("40701008", "Echocardiography", 30),
    ("71388002", "Total hip replacement", 60),
    ("119771000000106", "Cataract surgery", 65),
]

#: (SNOMED, display, minimum age). The CGM sensor is deliberately here:
#: cgm.pdhc is a live provider on this platform, so the simulator and the real
#: integration describe the same object rather than two different ones.
_DEVICES = [
    ("14106009", "Cardiac pacemaker", 55),
    ("69555007", "Implantable cardioverter defibrillator", 55),
    ("337414009", "Continuous glucose monitoring sensor", 10),
    ("25062003", "Insulin pump", 10),
    ("304120007", "Total hip prosthesis", 60),
    ("72506001", "Implantable hearing aid", 50),
]

#: (LOINC panel, display, [(LOINC, display, unit, low, high)]) -- the report
#: AND its results, because a report without results is the defect above.
_LAB_PANELS = [
    ("58410-2", "Complete blood count panel", [
        ("718-7", "Haemoglobin", "g/L", 115, 165),
        ("777-3", "Platelets", "10*9/L", 150, 400),
        ("6690-2", "Leukocytes", "10*9/L", 3.5, 10.0),
    ]),
    ("24323-8", "Comprehensive metabolic panel", [
        ("2160-0", "Creatinine", "umol/L", 50, 110),
        ("2345-7", "Glucose", "mmol/L", 4.0, 7.0),
        ("1751-7", "Albumin", "g/L", 35, 50),
    ]),
    ("24357-6", "Urinalysis panel", [
        ("5811-5", "Urine specific gravity", "1", 1.005, 1.030),
    ]),
]

#: Imaging: a report with a conclusion and no numeric result is CORRECT here,
#: unlike a lab panel. The distinction is the reason these are separate lists.
_IMAGING = [
    ("57021-8", "Chest X-ray", "No acute cardiopulmonary abnormality."),
    ("42272-5", "Abdominal ultrasound", "Liver and kidneys of normal appearance."),
    ("24590-2", "CT head without contrast", "No intracranial haemorrhage."),
]


def _narrative(text: str) -> dict:
    return {"status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{escape(text)}</div>'}


def _cc(system: str, code: str, display: str) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}],
            "text": display}


def _parse_birth(birth: date | str | None) -> date | None:
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
        return 40                      # a neutral default rather than a crash
    today = date.today()
    return max(0, today.year - birth.year
               - ((today.month, today.day) < (birth.month, birth.day)))


def _at_age(birth: date | None, years: float, rng: random.Random) -> str:
    """An ISO datetime when the patient was `years` old, jittered by months.

    Clamped to the past: a date in the future, or before birth, would be
    nonsense that a reader notices immediately.
    """
    if birth is None:
        return datetime.now(timezone.utc).isoformat()
    d = birth + timedelta(days=int(years * 365.25) + rng.randint(0, 120))
    today = date.today()
    if d > today:
        d = today - timedelta(days=rng.randint(1, 365))
    if d < birth:
        d = birth + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


def _recent(rng: random.Random, max_years_ago: int = 4) -> str:
    d = date.today() - timedelta(days=rng.randint(30, 365 * max_years_ago))
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


# --------------------------------------------------------------- immunisations

def _immunisations(ref: str, birth: date | None, rng: random.Random) -> list[dict]:
    out = []
    age = _age(birth)
    for code, display, at in rng.sample(_CHILDHOOD_VACCINES,
                                        rng.randint(2, 4)):
        if age < at:
            continue               # not old enough to have had it
        out.append({
            "resourceType": "Immunization",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display}, given at approximately age {at:g}."),
            "patient": {"reference": ref},
            "status": "completed",
            "vaccineCode": _cc("http://www.whocc.no/atc", code, display),
            "occurrenceDateTime": _at_age(birth, at, rng),
            "primarySource": True,
        })
    for code, display, min_age in _SEASONAL_VACCINES:
        if age < min_age or rng.random() > 0.5:
            continue
        out.append({
            "resourceType": "Immunization",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display}, seasonal dose."),
            "patient": {"reference": ref},
            "status": "completed",
            "vaccineCode": _cc("http://www.whocc.no/atc", code, display),
            "occurrenceDateTime": _recent(rng, 3),
            "primarySource": True,
        })
    return out


def _no_known(section: str, resource_type: str, ref: str,
              subject_field: str, text: str) -> dict:
    """An explicit "none known" for a recommended section.

    `occurrenceDateTime` is set on the Immunization even though there is no
    occurrence to date: FHIR makes `Immunization.occurrence[x]` required
    (1..1), so omitting it produces a structurally invalid resource. IPS may
    instead express this with a `data-absent-reason` extension on
    `_occurrenceDateTime`; that is not used here because the exact profile
    representation has not been verified against the published IG
    (euips_sections.CODES_VERIFIED is False), and satisfying the cardinality
    with a real date is the choice that cannot be wrong in a way a validator
    will not tell us about. Revisit when the IG is checked.
    """
    body = {
        "resourceType": resource_type,
        "id": str(uuid.uuid4()),
        "text": _narrative(text),
        subject_field: {"reference": ref},
        "status": "completed" if resource_type == "Immunization" else "unknown",
        ("vaccineCode" if resource_type == "Immunization" else "code"):
            euips.absent_coding(section),
    }
    if resource_type == "Immunization":
        body["occurrenceDateTime"] = datetime.now(timezone.utc).isoformat()
    return body


# ------------------------------------------------------------------ procedures

def _procedures(ref: str, birth: date | None, rng: random.Random) -> list[dict]:
    age = _age(birth)
    eligible = [p for p in _PROCEDURES if age >= p[2]]
    if not eligible:
        return []
    out = []
    for code, display, min_age in rng.sample(
            eligible, min(len(eligible), rng.randint(1, 2))):
        at = rng.uniform(min_age, max(min_age + 1, age))
        out.append({
            "resourceType": "Procedure",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display}, completed."),
            "subject": {"reference": ref},
            "status": "completed",
            "code": _cc("http://snomed.info/sct", code, display),
            "occurrenceDateTime": _at_age(birth, at, rng),
        })
    return out


# --------------------------------------------------------------------- devices

def _devices(ref: str, birth: date | None, rng: random.Random) -> list[dict]:
    """Device + DeviceUseStatement — THE section that did not exist at all."""
    age = _age(birth)
    eligible = [d for d in _DEVICES if age >= d[2]]
    if not eligible:
        return []
    code, display, min_age = rng.choice(eligible)
    device_id = str(uuid.uuid4())
    at = rng.uniform(min_age, max(min_age + 1, age))
    when = _at_age(birth, at, rng)
    return [
        {
            "resourceType": "Device",
            "id": device_id,
            "text": _narrative(f"{display}, in use."),
            "patient": {"reference": ref},
            "status": "active",
            "type": _cc("http://snomed.info/sct", code, display),
        },
        {
            "resourceType": "DeviceUseStatement",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{display} in use since {when[:10]}."),
            "subject": {"reference": ref},
            "status": "active",
            "device": {"reference": f"Device/{device_id}"},
            "timingDateTime": when,
        },
    ]


# ---------------------------------------------------------- diagnostic results

def _diagnostic_results(ref: str, birth: date | None,
                        rng: random.Random) -> list[dict]:
    """A report WITH its results — the gap measured in production.

    All 61 live DiagnosticReport rows carry no `result` at all. A lab section
    whose reports reference no observations is a header with a sentence, and
    the results are what a clinician reads.

    Imaging reports legitimately carry a conclusion and no numeric result, so
    the two are built differently rather than forced into one shape.
    """
    out: list[dict] = []
    when = _recent(rng, 2)

    panel_code, panel_display, analytes = rng.choice(_LAB_PANELS)
    result_refs = []
    for code, display, unit, lo, hi in analytes:
        obs_id = str(uuid.uuid4())
        val = round(rng.uniform(lo, hi), 2)
        out.append({
            "resourceType": "Observation",
            "id": obs_id,
            "text": _narrative(f"{display}: {val} {unit}."),
            "subject": {"reference": ref},
            "status": "final",
            "category": [_cc(
                "http://terminology.hl7.org/CodeSystem/observation-category",
                "laboratory", "Laboratory")],
            "code": _cc("http://loinc.org", code, display),
            # UCUM, as the guideline requires for units.
            "valueQuantity": {"value": val, "unit": unit,
                              "system": "http://unitsofmeasure.org",
                              "code": unit},
            "effectiveDateTime": when,
        })
        result_refs.append({"reference": f"Observation/{obs_id}"})

    out.append({
        "resourceType": "DiagnosticReport",
        "id": str(uuid.uuid4()),
        "text": _narrative(f"{panel_display}: {len(result_refs)} analytes reported."),
        "subject": {"reference": ref},
        "status": "final",
        "category": [_cc("http://loinc.org", "LAB", "Laboratory")],
        "code": _cc("http://loinc.org", panel_code, panel_display),
        "effectiveDateTime": when,
        # THE fix: the report points at its observations.
        "result": result_refs,
    })

    if rng.random() < 0.4:
        img_code, img_display, conclusion = rng.choice(_IMAGING)
        out.append({
            "resourceType": "DiagnosticReport",
            "id": str(uuid.uuid4()),
            "text": _narrative(f"{img_display}: {conclusion}"),
            "subject": {"reference": ref},
            "status": "final",
            "category": [_cc("http://loinc.org", "RAD", "Radiology")],
            "code": _cc("http://loinc.org", img_code, img_display),
            "effectiveDateTime": _recent(rng, 2),
            "conclusion": conclusion,
        })
    return out


_BUILDERS = {
    "immunisations": (_immunisations, "Immunization", "patient",
                      "No known immunisations."),
    "procedures": (_procedures, "Procedure", "subject",
                   "No known procedures."),
    "devices": (_devices, "Device", "patient", "No known devices."),
    "diagnostic_results": (_diagnostic_results, None, None, None),
}


def recommended_sections_for(patient_ref: str, birth: date | str | None = None,
                             *, rng: random.Random | None = None) -> list[dict]:
    """The four recommended sections for one patient, in dependency order.

    Observations are emitted BEFORE the DiagnosticReport that references them,
    so a caller writing the list in order never creates a dangling reference.

    Per section: content, or an explicit absence, or nothing — all three valid
    here, unlike the required three. `diagnostic_results` has no IPS absent
    code, so for that section the choice is content or nothing.
    """
    r = rng or random
    b = _parse_birth(birth)
    out: list[dict] = []

    for key in ("immunisations", "procedures", "devices", "diagnostic_results"):
        builder, rtype, subject_field, absent_text = _BUILDERS[key]
        if r.random() < PRESENCE_RATE[key]:
            built = builder(patient_ref, b, r)
            if built:
                out.extend(built)
                continue
            # Age ruled everything out (a child has no hip replacement). Fall
            # through to the absent/nothing choice rather than emitting an
            # empty section as though content were intended.
        if rtype and r.random() < ABSENT_SHARE:
            out.append(_no_known(key, rtype, patient_ref, subject_field,
                                 absent_text))
        # else: nothing at all, which is permitted for a recommended section.
    return out
