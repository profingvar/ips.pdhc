"""The euIPS section catalogue — #791, the decision that Phase C builds on.

Source: `docs/EU_Patient_Summary_ICD11.docx`, which lists the sections by
obligation level and names the terminologies. This module is DATA: the one
place that says which sections exist, what obligation each carries, which FHIR
resource types realise it, and how an explicitly-absent section is written.

## The decision recorded here (#791)

**Section content lives in `fhir_resources`. No new tables for clinical
content.** That table is already `resource_type` + `resource_json` (JSONB) +
`patient_guid`, indexed on type, patient and type+patient, and every euIPS
section IS a FHIR resource. Nine sibling services read ips; a per-section table
would mean new endpoints, new serialisers and a second source of truth for the
same clinical facts.

It also keeps the hybrid format intact. The guideline is explicit that every
section carries human-readable narrative *and* coded entries, and calls the
narrative the safety net — "what a clinician abroad sees". A FHIR resource
holds both (`text.div` plus the coded fields); typed columns would lose one.

**An explicitly-absent section is a real resource carrying the IPS
absent/unknown code.** The guideline requires it: *"you must state 'no known
allergies' rather than leave the section empty."* Writing it as an ordinary
row means no new storage, and it makes the three states distinguishable, which
is the whole problem:

| state | how it reads |
|---|---|
| `PRESENT` | a clinical resource of that type exists |
| `EXPLICITLY_ABSENT` | a resource exists carrying an absent/unknown code |
| `MISSING` | no row — which now unambiguously means "not generated" |

Before this, 110 of 150 patients had no rows in any section, and "no row" could
not be told apart from "the clinician recorded nothing to report".

**Section status is COMPUTED, not stored.** No `ips_section_status` table: a
second copy of a derivable fact is the shape that produced #779 (two identifier
spaces compared) and #771 (two GUIDs for one object). `status_for_patient()`
below derives it.

## Codes: NOT verified against the published IG

`CODES_VERIFIED = False`, and that is deliberate rather than lazy. The LOINC
section codes and the IPS absent/unknown codes below are written from knowledge
of the IPS implementation guide, not from a fetch of the published CodeSystem
and ValueSet. The plan's rule is that terminology is owned by plan.pdhc and
termbank.pdhc and that nothing here invents codes — so these carry a flag
rather than an implied warranty.

The source document also states the EHDS implementing acts with the technical
specifications were not confirmed adopted as of October 2026. So nothing built
on this catalogue may claim conformance; #799 says "all required sections
present", never "EU-conformant".

Verify before any such claim, and flip the flag in one place when done.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The IPS CodeSystem for "there is deliberately nothing here".
ABSENT_UNKNOWN_SYSTEM = "http://hl7.org/fhir/uv/ips/CodeSystem/absent-unknown-uv-ips"

# See the module docstring. One flag, one place to flip.
CODES_VERIFIED = False

REQUIRED = "required"
RECOMMENDED = "recommended"
OPTIONAL = "optional"
EU_ADDITION = "eu_addition"

OBLIGATION_ORDER = (REQUIRED, RECOMMENDED, OPTIONAL, EU_ADDITION)

PRESENT = "PRESENT"
EXPLICITLY_ABSENT = "EXPLICITLY_ABSENT"
MISSING = "MISSING"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    obligation: str
    resource_types: tuple[str, ...]
    #: LOINC code for the Composition section. UNVERIFIED — see CODES_VERIFIED.
    loinc: str | None = None
    #: The IPS absent/unknown code to use when there is nothing to report.
    #: None where IPS defines none, which is the case for sections whose plain
    #: absence is permitted.
    absent_code: str | None = None
    #: Where the generator must be careful not to produce nonsense.
    note: str = ""
    #: Resource types this section must NOT claim, where two sections share one
    #: type and are separated only by a field.
    excludes: tuple[str, ...] = field(default_factory=tuple)


SECTIONS: tuple[Section, ...] = (
    # ---- REQUIRED: may never be empty. A missing one invalidates the summary.
    Section("allergies", "Allergies and intolerances", REQUIRED,
            ("AllergyIntolerance",), "48765-2", "no-known-allergies",
            note="The guideline's own example of the absent-code rule."),
    Section("problems", "Problem list (active conditions)", REQUIRED,
            ("Condition",), "11450-4", "no-known-problems",
            note="ACTIVE conditions only. Resolved ones belong to "
                 "`past_illnesses`, and the two are told apart ONLY by "
                 "clinicalStatus — so a generator or section-builder that "
                 "ignores that field will put a resolved illness in the "
                 "active problem list."),
    Section("medications", "Medication summary", REQUIRED,
            ("MedicationStatement", "MedicationRequest"), "10160-0",
            "no-known-medications"),

    # ---- RECOMMENDED: absence is allowed, unlike the three above.
    Section("immunisations", "Immunisations", RECOMMENDED,
            ("Immunization",), "11369-6", "no-known-immunizations",
            note="Dates should follow from the patient's age rather than be "
                 "uniform random, or the schedule is implausible."),
    Section("procedures", "History of procedures", RECOMMENDED,
            ("Procedure",), "47519-4", "no-known-procedures"),
    Section("devices", "Medical devices and implants", RECOMMENDED,
            ("Device", "DeviceUseStatement"), "46264-8", "no-known-devices",
            note="THE MISSING ONE. No Device resource type exists in "
                 "fhir_resources at all (live types: Observation, Patient, "
                 "MedicationStatement, Condition, Immunization, "
                 "AllergyIntolerance, DiagnosticReport, Procedure)."),
    Section("diagnostic_results", "Diagnostic results (lab and imaging)",
            RECOMMENDED, ("DiagnosticReport", "Observation"), "30954-2",
            note="LOINC-coded with UCUM units per the guideline. Shares "
                 "Observation with vital signs and social history.",
            excludes=()),

    # ---- OPTIONAL
    Section("vital_signs", "Vital signs", OPTIONAL,
            ("Observation",), "8716-3"),
    Section("past_illnesses", "Past illnesses", OPTIONAL,
            ("Condition",), "11348-0",
            note="Condition with a resolved/inactive clinicalStatus. Must not "
                 "appear in `problems`."),
    Section("pregnancy", "Pregnancy (current and history)", OPTIONAL,
            ("Observation", "Condition"), "10162-6",
            note="MUST be consistent with sex and age. A pregnancy on a male "
                 "or an 80-year-old is generated nonsense that the first "
                 "clinician to look will notice."),
    Section("social_history", "Social history", OPTIONAL,
            ("Observation",), "29762-2",
            note="Smoking and alcohol status."),
    Section("functional_status", "Functional status", OPTIONAL,
            ("Observation", "ClinicalImpression"), "47420-5"),
    Section("plan_of_care", "Plan of care", OPTIONAL,
            ("CarePlan",), "18776-5"),
    Section("advance_directives", "Advance directives", OPTIONAL,
            ("Consent",), "42348-3",
            note="A FHIR Consent resource in fhir_resources, deliberately NOT "
                 "a patient_consents row: that table is cohesive-care consent "
                 "(Lag 2022:913 §5) and is read by /consents/check, which "
                 "request.pdhc and contract.pdhc both call. An advance "
                 "directive must not be mistakable for a care consent."),

    # ---- EU ADDITIONS (eHealth Network / Xt-EHR building blocks)
    Section("alerts", "Medical alerts", EU_ADDITION,
            ("Flag",), None,
            note="LOINC code not established for this EU addition — left None "
                 "rather than guessed. Safety-weighted: it is what a clinician "
                 "abroad is meant to see first. A SIMULATED alert must stay "
                 "distinguishable from a COMPUTED one from request.pdhc's "
                 "alerting path, which is the MDR-relevant surface."),
    Section("travel_history", "Travel history", EU_ADDITION,
            ("Observation",), None,
            note="Dates should relate to any relevant condition rather than "
                 "float free, since travel history exists for "
                 "infectious-disease reasoning."),
    Section("patient_provided", "Patient-provided information", EU_ADDITION,
            ("Observation", "QuestionnaireResponse"), None,
            note="Distinguished by the resource's source/performer, not by a "
                 "separate type. The distinction IS the section: information "
                 "the patient asserted carries different weight, and unmarked "
                 "it is decorative."),
)

BY_KEY: dict[str, Section] = {s.key: s for s in SECTIONS}
REQUIRED_KEYS: tuple[str, ...] = tuple(
    s.key for s in SECTIONS if s.obligation == REQUIRED)


def absent_coding(section_key: str) -> dict | None:
    """The CodeableConcept to put on a resource that asserts "nothing here".

    None where IPS defines no absent code for the section, in which case plain
    absence is the correct representation and a caller must not invent one.
    """
    s = BY_KEY[section_key]
    if not s.absent_code:
        return None
    return {"coding": [{"system": ABSENT_UNKNOWN_SYSTEM,
                        "code": s.absent_code}],
            "text": f"No information: {s.title}"}


def is_absent_assertion(resource_json: dict | None) -> bool:
    """True when this resource asserts an absent/unknown section.

    Looks for the IPS CodeSystem anywhere in the resource's own coding fields.
    Checked across the handful of places a code sits on these resource types
    rather than one, because AllergyIntolerance, Condition and
    MedicationStatement do not agree on the field name.
    """
    if not isinstance(resource_json, dict):
        return False
    for key in ("code", "medicationCodeableConcept"):
        cc = resource_json.get(key)
        if isinstance(cc, dict):
            for coding in cc.get("coding") or []:
                if isinstance(coding, dict) and \
                        coding.get("system") == ABSENT_UNKNOWN_SYSTEM:
                    return True
    return False


def status_for_resources(rows) -> dict[str, str]:
    """Section -> PRESENT / EXPLICITLY_ABSENT / MISSING for one patient.

    `rows` is an iterable of objects with `.resource_type` and
    `.resource_json` — i.e. that patient's `fhir_resources`. Computed, never
    stored: see the module docstring.

    A section with BOTH a real entry and an absent assertion reads as PRESENT.
    Real content wins, because an absent assertion left behind after data
    arrived is stale bookkeeping and must not hide the data.
    """
    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r.resource_type, []).append(r)

    out: dict[str, str] = {}
    for s in SECTIONS:
        real = 0
        absent = 0
        for rtype in s.resource_types:
            for r in by_type.get(rtype, []):
                if is_absent_assertion(r.resource_json):
                    absent += 1
                else:
                    real += 1
        if real:
            out[s.key] = PRESENT
        elif absent:
            out[s.key] = EXPLICITLY_ABSENT
        else:
            out[s.key] = MISSING
    return out


def is_conformant(status: dict[str, str]) -> bool:
    """True when every REQUIRED section is PRESENT or EXPLICITLY_ABSENT.

    Deliberately narrow, and deliberately not called `is_eu_conformant`: this
    checks the obligation levels in the source document, which itself says the
    EHDS technical specifications were not confirmed adopted. See #799.
    """
    return all(status.get(k) in (PRESENT, EXPLICITLY_ABSENT)
               for k in REQUIRED_KEYS)
