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
    #: How to tell this section's resources from another section's of the SAME
    #: type. REQUIRED whenever `resource_types` overlaps another section --
    #: asserted by a test. See `_DISCRIMINATORS` and why it matters.
    discriminator: str | None = None


SECTIONS: tuple[Section, ...] = (
    # ---- REQUIRED: may never be empty. A missing one invalidates the summary.
    Section("allergies", "Allergies and intolerances", REQUIRED,
            ("AllergyIntolerance",), "48765-2", "no-known-allergies",
            note="The guideline's own example of the absent-code rule."),
    Section("problems", "Problem list (active conditions)", REQUIRED,
            ("Condition",), "11450-4", "no-known-problems",
            discriminator="condition_active",
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
            discriminator="diagnostic",
            note="LOINC-coded with UCUM units per the guideline. Shares "
                 "Observation with vital signs and social history.",
            excludes=()),

    # ---- OPTIONAL
    Section("vital_signs", "Vital signs", OPTIONAL,
            ("Observation",), "8716-3", discriminator="obs_vital_signs"),
    Section("past_illnesses", "Past illnesses", OPTIONAL,
            ("Condition",), "11348-0", discriminator="condition_resolved",
            note="Condition with a resolved/inactive clinicalStatus. Must not "
                 "appear in `problems`."),
    Section("pregnancy", "Pregnancy (current and history)", OPTIONAL,
            ("Observation", "Condition"), "10162-6",
            discriminator="pregnancy_code",
            note="MUST be consistent with sex and age. A pregnancy on a male "
                 "or an 80-year-old is generated nonsense that the first "
                 "clinician to look will notice."),
    Section("social_history", "Social history", OPTIONAL,
            ("Observation",), "29762-2", discriminator="obs_social_history",
            note="Smoking and alcohol status."),
    Section("functional_status", "Functional status", OPTIONAL,
            ("Observation", "ClinicalImpression"), "47420-5",
            discriminator="obs_survey"),
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
            ("Observation",), None, discriminator="travel_code",
            note="Dates should relate to any relevant condition rather than "
                 "float free, since travel history exists for "
                 "infectious-disease reasoning."),
    Section("patient_provided", "Patient-provided information", EU_ADDITION,
            ("Observation", "QuestionnaireResponse"), None,
            discriminator="patient_asserted",
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


#: Every field on these resource types that can carry the section's own code.
#: Resource types do NOT agree on the name, and getting this list wrong makes
#: an absent assertion undetectable -- which silently turns EXPLICITLY_ABSENT
#: back into MISSING for a REQUIRED section.
#:
#: `medication` is here because that is what this codebase actually writes:
#: all 119 live MedicationStatement rows use it. The first version of this
#: function checked only `code` and `medicationCodeableConcept`, so a
#: medications absent-assertion -- one of the three required sections -- could
#: never have been recognised. Found by starting #793, after #791 had shipped.
_CODE_BEARING_FIELDS = (
    "code",                      # AllergyIntolerance, Condition, Observation, Flag
    "medication",                # MedicationStatement, as written here
    "medicationCodeableConcept",  # the R4 spelling, tolerated on input
    "vaccineCode",               # Immunization
    "type",                      # Device; also AllergyIntolerance.type in R5
)


def _codings(value) -> list:
    """Every coding in `value`, whether it is a CodeableConcept or an R5
    CodeableReference (`{"concept": {...}}`). Returns [] for anything else,
    including the plain strings some R4 fields hold (AllergyIntolerance.type),
    so a wrong guess is inert rather than an exception.
    """
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("concept"), dict):       # CodeableReference
        value = value["concept"]
    out = []
    for coding in value.get("coding") or []:
        if isinstance(coding, dict):
            out.append(coding)
    return out


def is_absent_assertion(resource_json: dict | None) -> bool:
    """True when this resource asserts an absent/unknown section.

    Looks for the IPS CodeSystem across every field that can carry the
    section's code — see `_CODE_BEARING_FIELDS` for why that list, and why
    getting it wrong is worse than it looks.
    """
    if not isinstance(resource_json, dict):
        return False
    for key in _CODE_BEARING_FIELDS:
        for coding in _codings(resource_json.get(key)):
            if coding.get("system") == ABSENT_UNKNOWN_SYSTEM:
                return True
    return False


#: Pregnancy codes. Small and explicit: pregnancy is the section where a wrong
#: attribution is most visible, and the ticket's own warning is that a
#: pregnancy on a male or an 80-year-old is generated nonsense a clinician
#: notices immediately. UNVERIFIED like every code here (CODES_VERIFIED).
PREGNANCY_CODES = frozenset({
    "82810-3",      # LOINC Pregnancy status
    "11636-8",      # LOINC Number of live births
    "11640-0",      # LOINC Number of pregnancies
    "77386006",     # SNOMED Pregnant
    "102874004",    # SNOMED Possible pregnancy
})

#: Travel-history codes. #795 left this EMPTY on purpose, because no code is
#: established for this EU addition and a guess would make the section claim
#: observations that are not travel history.
#:
#: #796 settles it PROVISIONALLY on SNOMED 420008001 ("Travel"). That is a
#: choice, not a verified binding: it is covered by CODES_VERIFIED = False, and
#: this is the single place to change when the terminology is checked against
#: the published IG. Recorded rather than asserted.
TRAVEL_CODES: frozenset[str] = frozenset({"420008001"})

#: HL7 observation-category codes, used to tell Observation sections apart.
_VITAL_SIGNS_CATEGORIES = frozenset({"vital-signs"})
_SOCIAL_HISTORY_CATEGORIES = frozenset({"social-history"})
_DIAGNOSTIC_CATEGORIES = frozenset({"laboratory", "imaging"})
#: `survey` is the closest standard observation-category for functional status;
#: HL7 defines no `functional-status` code. Recorded rather than invented.
_SURVEY_CATEGORIES = frozenset({"survey", "activity"})

#: Codes that belong to a section MORE SPECIFIC than social history, while
#: still carrying the `social-history` category. `obs_social_history` subtracts
#: these so the general section does not swallow the specific ones.
_MORE_SPECIFIC_SOCIAL_CODES = PREGNANCY_CODES | TRAVEL_CODES

_ACTIVE_CONDITION_STATUSES = frozenset({"active", "recurrence", "relapse"})
_RESOLVED_CONDITION_STATUSES = frozenset({"inactive", "resolved", "remission"})


def _categories(resource_json: dict) -> set[str]:
    out = set()
    for cat in resource_json.get("category") or []:
        if isinstance(cat, dict):
            for c in cat.get("coding") or []:
                if isinstance(c, dict) and c.get("code"):
                    out.add(c["code"])
        elif isinstance(cat, str):
            out.add(cat)
    return out


def _own_codes(resource_json: dict) -> set[str]:
    out = set()
    for key in _CODE_BEARING_FIELDS:
        for coding in _codings(resource_json.get(key)):
            if coding.get("code"):
                out.add(coding["code"])
    return out


def _clinical_status(resource_json: dict) -> set[str]:
    return {c.get("code") for c in _codings(resource_json.get("clinicalStatus"))
            if c.get("code")}


def _is_patient_asserted(resource_json: dict) -> bool:
    """True when the PATIENT, not a clinician, is the source.

    That distinction IS the patient-provided section: information the patient
    asserted carries different weight, and unmarked the section is decorative.
    In FHIR it shows up as the performer (or informant) being the subject.
    """
    subject = ((resource_json.get("subject") or {}).get("reference")
               or (resource_json.get("patient") or {}).get("reference"))
    if not subject:
        return False
    for p in resource_json.get("performer") or []:
        if isinstance(p, dict) and p.get("reference") == subject:
            return True
    src = resource_json.get("source")
    if isinstance(src, dict) and src.get("reference") == subject:
        return True
    return False


def section_matches(section: Section, resource_type: str,
                    resource_json: dict) -> bool:
    """Does this resource belong to this section?

    Needed because **Condition is shared by 3 sections and Observation by 7**.
    Without discrimination a single vital-sign Observation made all seven read
    PRESENT, and -- conformance-affecting -- a patient with only a RESOLVED
    condition made `problems` read PRESENT while the active problem list was
    empty. That was the shipped behaviour of #791 until #795 exposed it.
    """
    if resource_type not in section.resource_types:
        return False
    d = section.discriminator
    if d is None:
        return True                       # the type is unique to this section
    if d == "condition_active":
        return bool(_clinical_status(resource_json) & _ACTIVE_CONDITION_STATUSES)
    if d == "condition_resolved":
        return bool(_clinical_status(resource_json) & _RESOLVED_CONDITION_STATUSES)
    if d == "pregnancy_code":
        return bool(_own_codes(resource_json) & PREGNANCY_CODES)
    if d == "travel_code":
        return bool(_own_codes(resource_json) & TRAVEL_CODES)
    if d == "obs_vital_signs":
        return bool(_categories(resource_json) & _VITAL_SIGNS_CATEGORIES)
    if d == "obs_social_history":
        # SUBTRACTIVE. Pregnancy and travel history are MORE SPECIFIC sections
        # that legitimately sit in the `social-history` category, so a
        # category-only rule made one travel observation mark both
        # `social_history` and `travel_history` PRESENT -- the third instance
        # of this over-reporting class, after the seven-section Observation
        # overlap and the active/resolved Condition overlap.
        #
        # The general section yields to the specific one: whatever carries a
        # pregnancy or travel code belongs to that section and not to this.
        if not (_categories(resource_json) & _SOCIAL_HISTORY_CATEGORIES):
            return False
        return not (_own_codes(resource_json) & _MORE_SPECIFIC_SOCIAL_CODES)
    if d == "obs_survey":
        # SUBTRACTIVE, for the same reason as obs_social_history. A
        # patient-reported outcome legitimately carries the `survey` category,
        # so a category-only rule made one patient-provided observation mark
        # both `functional_status` and `patient_provided`.
        #
        # `patient_provided` is a claim about PROVENANCE, and it is the more
        # specific one: a clinician-recorded survey is functional status, while
        # the same survey asserted by the patient belongs to the
        # patient-provided section. The general yields to the specific.
        if resource_type == "ClinicalImpression":
            return True
        if not (_categories(resource_json) & _SURVEY_CATEGORIES):
            return False
        return not _is_patient_asserted(resource_json)
    if d == "diagnostic":
        if resource_type == "DiagnosticReport":
            return True
        return bool(_categories(resource_json) & _DIAGNOSTIC_CATEGORIES)
    if d == "patient_asserted":
        return _is_patient_asserted(resource_json)
    raise ValueError(f"unknown discriminator {d!r} on section {section.key!r}")


def absent_section_key(resource_json: dict | None) -> str | None:
    """Which section this absent assertion is about, by its own code.

    Exact rather than inferred: the IPS absent codes are section-specific, so
    an absent assertion is attributed to its own section and to no other. A
    "no known problems" Condition must not also satisfy `past_illnesses`.
    """
    if not isinstance(resource_json, dict):
        return None
    codes = _own_codes(resource_json)
    for sec in SECTIONS:
        if sec.absent_code and sec.absent_code in codes:
            return sec.key
    return None


def status_for_resources(rows) -> dict[str, str]:
    """Section -> PRESENT / EXPLICITLY_ABSENT / MISSING for one patient.

    `rows` is an iterable of objects with `.resource_type` and
    `.resource_json` — i.e. that patient's `fhir_resources`. Computed, never
    stored: see the module docstring.

    A section with BOTH a real entry and an absent assertion reads as PRESENT.
    Real content wins, because an absent assertion left behind after data
    arrived is stale bookkeeping and must not hide the data.
    """
    real: dict[str, int] = {s.key: 0 for s in SECTIONS}
    absent: dict[str, int] = {s.key: 0 for s in SECTIONS}

    for r in rows:
        rj = r.resource_json if isinstance(r.resource_json, dict) else {}
        if is_absent_assertion(rj):
            # Attributed by its own absent code, to exactly one section.
            key = absent_section_key(rj)
            if key is not None:
                absent[key] += 1
            continue
        for s in SECTIONS:
            if section_matches(s, r.resource_type, rj):
                real[s.key] += 1

    out: dict[str, str] = {}
    for s in SECTIONS:
        if real[s.key]:
            out[s.key] = PRESENT
        elif absent[s.key]:
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
