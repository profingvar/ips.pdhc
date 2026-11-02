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

## Codes: VERIFIED against the published IG, 2026-11-02 (#885)

`CODES_VERIFIED = True`. Every LOINC section code and every absent/unknown
code below was fetched from the published guides and compared, rather than
written from knowledge of them. The record is `CODES_VERIFIED_AGAINST`, so a
reader can tell WHICH document was checked and when — a bare True would be a
weaker claim than the False it replaced.

**All 16 LOINC section codes are correct**, as is `Composition.type` 60591-5
(used by `ips_generator`), the absent/unknown CodeSystem URL, and all six
absent codes.

Three things the fetch established that the codes themselves do not say:

1. **EPS is an R4 guide.** `composition-eu-eps` is built on FHIR R4 and targets
   IPS 2.0.1, which is R4; this platform is R5 by the EPS A1 ruling. So the
   profile named `deviceUseStatement-eu-eps` is the R4 spelling of what R5
   calls `DeviceUsage` — #898's correction was right FOR THIS PLATFORM, and the
   difference is a version gap, not an error on either side.

2. **EPS makes two sections 1..1 that are RECOMMENDED here** —
   `sectionProceduresHx` (47519-4) and `sectionMedicalDevices` (46264-8). The
   codes agree; the obligations do not. `Composition.section` is 5..* in EPS,
   and those two are the fourth and fifth. NOT changed here: the obligation
   tier drives `conformant` and the mock generator, and this catalogue serves
   IPS domestically where both are recommended. One catalogue cannot hold two
   obligation sets by overwriting one of them — see #906.

3. **EPS has no past-illnesses section.** 11348-0 is absent from the EPS
   Composition entirely; it is an IPS section. `EPS_TEXT_SECTIONS`'s note on
   11329-0 already anticipated this ("once 11348-0 is unprofiled") and #880
   decided against moving resolved conditions into a free-text section, because
   that destroys their coding. The fetch turns that anticipation into a
   measurement.

**This does NOT make anything EU-conformant, and the rule is unchanged.** The
EPS document is version 1.0.0-ballot (ci-build 150), "STU 1 Ballot 1",
generated 2026-06-06, and its own pages say it is not an authorized
publication. Verified codes mean the codes are right; they say nothing about
cardinality, profile conformance, or the EHDS implementing acts. #799's rule
stands: say "all required sections present", never "EU-conformant".
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The IPS CodeSystem for "there is deliberately nothing here".
ABSENT_UNKNOWN_SYSTEM = "http://hl7.org/fhir/uv/ips/CodeSystem/absent-unknown-uv-ips"

# See the module docstring. One flag, one place to flip.
CODES_VERIFIED = True

#: WHAT was checked, WHEN, and from WHERE — #885 asked for this record and not
#: merely the flag, because "verified" against an unnamed document is not a
#: verifiable claim. A future reader comparing against a newer ballot needs to
#: know which one this was.
CODES_VERIFIED_AGAINST = {
    "verified_on": "2026-11-02",
    "guides": (
        {
            "name": "HL7 Europe Patient Summary (EPS)",
            "url": "https://hl7.eu/fhir/eps/"
                   "StructureDefinition-composition-eu-eps.html",
            "version": "1.0.0-ballot (ci-build 150), STU 1 Ballot 1",
            "generated": "2026-06-06",
            "fhir_version": "R4",
            "authorized_publication": False,
            "checked": "all 17 Composition.section slices, their LOINC codes "
                       "and cardinalities; Composition.type 60591-5",
        },
        {
            "name": "HL7 International Patient Summary (IPS)",
            "url": "https://hl7.org/fhir/uv/ips/"
                   "CodeSystem-absent-unknown-uv-ips.html",
            "version": "1.1.0 (STU 1 Update 1)",
            "fhir_version": "R4",
            "authorized_publication": True,
            "checked": "the absent/unknown CodeSystem URL and all six absent "
                       "codes used here",
        },
    ),
    # Recorded because #885 asked for disagreements to be recorded, and these
    # are the only ones found. Neither is a wrong code.
    "divergences": (
        "EPS makes sectionProceduresHx (47519-4) and sectionMedicalDevices "
        "(46264-8) 1..1; both are RECOMMENDED in this catalogue, which also "
        "serves IPS domestically. Codes agree, obligations differ. See #906.",
        "EPS defines no section for 11348-0 (past illnesses); it is an IPS "
        "section. #880 already decided resolved conditions stay domestic "
        "rather than move into EPS's free-text 11329-0.",
        "EPS is an R4 guide and this platform is R5 (EPS A1), so EPS's "
        "deviceUseStatement profile is the R4 spelling of R5's DeviceUsage. "
        "A version gap, not an error — #898.",
    ),
    # What this flag does NOT cover.
    "not_covered": (
        "euips_header.CODES_VERIFIED stays False: its scope includes R5 "
        "element shapes, and an R4 guide cannot verify those. One flag per "
        "module, so a verified module is not vouched for by an unverified one.",
        "Cardinality and profile conformance. Verified codes are not "
        "conformance; #799's rule is unchanged.",
    ),
}

REQUIRED = "required"
RECOMMENDED = "recommended"
OPTIONAL = "optional"
EU_ADDITION = "eu_addition"

OBLIGATION_ORDER = (REQUIRED, RECOMMENDED, OPTIONAL, EU_ADDITION)

# ---------------------------------------------------------------------------
# Profiles — #906.
#
# EPS and IPS agree on every section CODE and disagree on two obligations:
# `sectionProceduresHx` (47519-4) and `sectionMedicalDevices` (46264-8) are
# 1..1 in EPS and RECOMMENDED here, measured by #885 against
# `composition-eu-eps`. `Composition.section` is 5..* in EPS, and those two
# are the fourth and fifth.
#
# One catalogue cannot hold two obligation sets by overwriting one, so it
# holds both — and `is_conformant` takes the profile as a MANDATORY
# keyword-only argument. That is the whole design decision: the failure mode
# to protect against is not a wrong answer, it is a caller who never noticed
# there were two questions and got the other one's answer silently. A default
# would reintroduce exactly that.
PROFILE_IPS = "ips"
PROFILE_EPS = "eps"
PROFILES = (PROFILE_IPS, PROFILE_EPS)

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
    #: The obligation under the EPS profile, where it DIFFERS from `obligation`
    #: above (#906). None means "the same", so only a divergence is written
    #: down and a reader does not have to compare two columns to find one.
    #:
    #: Measured by #885 against `composition-eu-eps`: EPS makes
    #: `sectionProceduresHx` and `sectionMedicalDevices` 1..1, where this
    #: catalogue has them RECOMMENDED for the domestic IPS surface. The codes
    #: agree; only the obligation differs.
    obligation_eps: str | None = None

    @property
    def obligation_for(self) -> dict:
        """Obligation per profile, so a caller cannot read the wrong one by
        forgetting that a second exists."""
        return {PROFILE_IPS: self.obligation,
                PROFILE_EPS: self.obligation_eps or self.obligation}


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
            ("Procedure",), "47519-4", "no-known-procedures",
            obligation_eps=REQUIRED,
            note="EPS makes this 1..1 (#885 measured it on "
                 "`sectionProceduresHx`); it is RECOMMENDED on the domestic "
                 "IPS surface. See `obligation_eps` and #906 — the codes "
                 "agree, only the obligation differs."),
    Section("devices", "Medical devices and implants", RECOMMENDED,
            ("Device", "DeviceUsage"), "46264-8", "no-known-devices",
            obligation_eps=REQUIRED,
            note="R5 names this resource DeviceUsage; R4 called it "
                 "DeviceUseStatement, and this catalogue said the R4 name while "
                 "the service declares fhirVersion 5.0.0 — corrected by #898. "
                 "Old rows are still matched, via LEGACY_RESOURCE_TYPES; this "
                 "tuple is CANONICAL because it is served over the API "
                 "(/patients/<g>/euips-status) and so describes what to WRITE. "
                 "EPS makes this section 1..1, and the implant list is real "
                 "data in alert.pdhc (ICD-10-SE Z95.x) rather than something to "
                 "generate — see #886. The previous note here claimed no Device "
                 "type existed at all; that had been wrong since 2026-10-07, "
                 "when #794 added the builder."),
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
            ("Flag",), "104605-1",
            note="LOINC from the EPS specification (docs/EPS_patientoversikt.docx "
                 "and EPS_sektioner_vokabularer.xlsx, both 2026-10-30), filled "
                 "by #881. It was None before that — left None rather than "
                 "guessed, which is why there was nothing to unpick when the "
                 "real value arrived. STILL UNVERIFIED against the published IG: "
                 "the source is a CI-build of a STU 1 Ballot, so CODES_VERIFIED "
                 "stays False and only #885 may change it. "
                 "Safety-weighted: it is what a clinician abroad is meant to see "
                 "first. A SIMULATED alert must stay distinguishable from a "
                 "COMPUTED one from request.pdhc's alerting path, which is the "
                 "MDR-relevant surface."),
    Section("travel_history", "Travel history", EU_ADDITION,
            ("Observation",), "10182-4", discriminator="travel_code",
            note="LOINC from the EPS specification (2026-10-30), filled by "
                 "#881; was None. UNVERIFIED against the published IG — "
                 "CODES_VERIFIED stays False, see #885. Not to be confused with "
                 "TRAVEL_CODES: this is the COMPOSITION SECTION code, while "
                 "TRAVEL_CODE holds the code on the Observation itself — LOINC "
                 "94651-7 since #885 verified it against the EPS profile, which "
                 "FIXES it; the SNOMED 420008001 that #795 chose provisionally "
                 "survives in TRAVEL_CODES for matching stored rows only. "
                 "Dates should relate to any relevant condition rather than "
                 "float free, since travel history exists for "
                 "infectious-disease reasoning."),
    Section("patient_provided", "Patient-provided information", EU_ADDITION,
            ("Observation", "QuestionnaireResponse"), None,
            discriminator="patient_asserted",
            note="LOINC stays None DELIBERATELY, and that is a decision rather "
                 "than a gap (#880): EPS does not profile this section at all. "
                 "It has Patient Story (81338-6) and Patient History "
                 "(11329-0); neither means 'information the patient asserted'. "
                 "So this section is DOMESTIC — kept here with its coded "
                 "content, and not carried as such into the international "
                 "export format. Do not fill this in to make the catalogue look "
                 "complete. "
                 "Distinguished by the resource's source/performer, not by a "
                 "separate type. The distinction IS the section: information "
                 "the patient asserted carries different weight, and unmarked "
                 "it is decorative."),
)

#: Resource-type spellings this service no longer WRITES but must still READ.
#:
#: `fhir_resources.resource_type` is a plain `String(64)`, so rows keep whatever
#: string was written when they were created. R5 renamed DeviceUseStatement to
#: DeviceUsage (#898), and rather than migrate rows blind — the production count
#: was unavailable when the change was made — the old spelling is accepted on
#: READ and never produced on WRITE.
#:
#: Deliberately NOT merged into `Section.resource_types`: that tuple is served
#: over the API and therefore describes what a producer should write. An alias
#: published there is an invitation to keep using it.
#:
#: Removal condition: once `select count(*) from fhir_resources where
#: resource_type = 'DeviceUseStatement'` is 0 in every deployment, this entry
#: and the normalisation in `section_matches` can go together.
LEGACY_RESOURCE_TYPES: dict[str, str] = {
    "DeviceUseStatement": "DeviceUsage",
}


def canonical_resource_type(resource_type: str) -> str:
    """The spelling this service writes today, for a possibly older row."""
    return LEGACY_RESOURCE_TYPES.get(resource_type, resource_type)


#: Sections the EPS specification defines that this service does NOT carry,
#: because they are FREE TEXT and nothing here produces or stores narrative.
#:
#: **Deliberately NOT in `SECTIONS`** (#882). That tuple drives the
#: resource-derived report: `status_for_resources` answers PRESENT /
#: EXPLICITLY_ABSENT / MISSING from the rows a patient has. These two are not
#: resource-backed, so either answer would be wrong —
#:
#:   - MISSING would read as "this patient lacks it", when the truth is "we do
#:     not carry this section at all". Every patient would show two permanent
#:     MISSING rows, which is how a coverage report trains its reader to skim.
#:   - a fourth status would have to be handled by four consumers, and one of
#:     them breaks SILENTLY: `euips_report` uses
#:     `all(v == MISSING for v in st.values())` to spot a patient with nothing
#:     at all, and a status that is never MISSING makes that test permanently
#:     false.
#:
#: Declaring them here instead keeps `SECTIONS` meaning "resource-derived",
#: which is what every consumer already assumes, and says something more
#: useful than a status: the section is DECLARED and not CARRIED.
#:
#: Content generation waits on a document builder. The euIPS path assembles no
#: Composition today — `euips_header.composition_header()` builds the header
#: only, and the `Composition` with `"section"` in `ips_generator.py` belongs to
#: the older IPS-card path. Narrative has nowhere to live until #896 (EPS B7)
#: builds the export document, and inventing a half-generator before then would
#: produce text no surface reads.
#:
#: LOINC codes from the EPS specification of 2026-10-30, same provenance and
#: same caveat as the two filled by #881: the source is a CI-build of a STU 1
#: Ballot, so CODES_VERIFIED stays False and #885 governs it.
EPS_TEXT_SECTIONS: tuple[dict, ...] = (
    {
        "loinc": "81338-6",
        "title": "Patient Story",
        "title_sv": "Patientens berättelse",
        "eps_unique": False,
        "note": "Free text. NOT the same as `patient_provided`, which is "
                "information the patient ASSERTED, distinguished by the "
                "resource's source/performer. #880 decided patient_provided "
                "stays DOMESTIC and is not exported, so these two do not "
                "merge and neither substitutes for the other.",
    },
    {
        "loinc": "11329-0",
        "title": "Patient History",
        "title_sv": "Sjukdomshistoria",
        "eps_unique": True,
        "note": "Free text, and EPS-unique — IPS has no counterpart. It is "
                "the only plausible international home for resolved "
                "conditions once 11348-0 is unprofiled, and #880 decided "
                "AGAINST moving them: `past_illnesses` stays domestic with "
                "its coded content, because mapping coded resolved "
                "conditions into a free-text section destroys the coding. "
                "`euips_sections` already warns that `problems` and "
                "`past_illnesses` are told apart ONLY by clinicalStatus, so a "
                "merge here would also put resolved illnesses in the ACTIVE "
                "problem list.",
    },
)


BY_KEY: dict[str, Section] = {s.key: s for s in SECTIONS}
#: The IPS required set — the DOMESTIC surface, which is what this service
#: serves day to day. Kept under its original name because it is read in four
#: places and over the API; `required_keys(PROFILE_EPS)` is the other answer.
REQUIRED_KEYS: tuple[str, ...] = tuple(
    s.key for s in SECTIONS if s.obligation == REQUIRED)


def required_keys(profile: str) -> tuple[str, ...]:
    """The sections that may not be MISSING under `profile` (#906).

    Raises on an unknown profile rather than returning an empty tuple: an
    empty required set makes EVERY patient conformant, which is the one
    wrong answer that looks like good news.
    """
    if profile not in PROFILES:
        raise ValueError(
            f"unknown profile {profile!r}; expected one of {PROFILES}")
    return tuple(s.key for s in SECTIONS
                 if s.obligation_for[profile] == REQUIRED)


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
#: The code to WRITE on a travel-history Observation, verified by #885 against
#: the EPS profile `observation-travel-eu-eps`, which FIXES `Observation.code`
#: to LOINC 94651-7. It was previously SNOMED `420008001`, chosen provisionally
#: by #795 because no code was established — a reasonable guess, and wrong.
TRAVEL_CODE_SYSTEM = "http://loinc.org"
TRAVEL_CODE = "94651-7"

#: Codes that MATCH a travel-history Observation. Wider than what we write, on
#: purpose: `420008001` is in rows already stored, and dropping it from the
#: matcher would make those rows stop being travel history — the section would
#: silently go from PRESENT to MISSING for every patient generated before
#: #885. Same courtesy `LEGACY_RESOURCE_TYPES` pays the R4 resource name.
TRAVEL_CODE_LEGACY = "420008001"
TRAVEL_CODES: frozenset[str] = frozenset({TRAVEL_CODE, TRAVEL_CODE_LEGACY})

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
    if canonical_resource_type(resource_type) not in section.resource_types:
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


def is_conformant(status: dict[str, str], *, profile: str) -> bool:
    """True when every section REQUIRED BY `profile` is PRESENT or
    EXPLICITLY_ABSENT.

    Deliberately narrow, and deliberately not called `is_eu_conformant`: this
    checks obligation levels, and #885 measured that the EPS guide is a ballot
    which its own pages call unauthorised. See #799.

    `profile` is keyword-only and has NO DEFAULT, on purpose (#906). EPS and
    IPS require different section sets, and the failure mode worth preventing
    is not a wrong answer — it is a caller who never noticed there were two
    questions and silently received the other one's answer. A default would
    reintroduce precisely that, and it would do so most quietly for the
    callers written before the second profile existed.

    This is the same lesson as #779 (two identifier spaces compared as if they
    were one) and #760 (a read allowlist that also granted writes): where two
    things can be confused, make the code say which one it means.
    """
    return all(status.get(k) in (PRESENT, EXPLICITLY_ABSENT)
               for k in required_keys(profile))


def conformance(status: dict[str, str]) -> dict:
    """Both answers at once, for a surface that should report rather than
    choose — `{profile: {"conformant": bool, "required_missing": [...]}}`.

    Offered so a diagnostic endpoint does not have to pick a profile on its
    caller's behalf, which is the choice that makes `conformant` ambiguous in
    the first place.
    """
    out = {}
    for prof in PROFILES:
        missing = [k for k in required_keys(prof)
                   if status.get(k) == MISSING]
        out[prof] = {
            "conformant": is_conformant(status, profile=prof),
            "required_missing": missing,
        }
    return out
