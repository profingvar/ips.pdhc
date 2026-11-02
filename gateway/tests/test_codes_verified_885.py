"""EPS B5 (#885) — the codes, checked against the published guides.

`CODES_VERIFIED` was False because the LOINC section codes and the IPS
absent/unknown codes had been written from knowledge of the guides rather
than fetched from them. #885's deliverable was to fetch, compare, record
which guide and when, and only then flip the flag — and to record any
disagreement, because the document is what EPS B1 and B2 were built from.

WHAT WAS FETCHED, 2026-11-02:

  - HL7 Europe Patient Summary, `composition-eu-eps`,
    v1.0.0-ballot (ci-build 150), generated 2026-06-06, built on FHIR R4.
    All 17 `Composition.section` slices with their codes and cardinalities,
    and `Composition.type`.
  - HL7 IPS, `CodeSystem-absent-unknown-uv-ips`, v1.1.0 (STU 1 Update 1).
    The CodeSystem URL and all six absent codes used here.
  - HL7 FHIR R5, `device.html` and `deviceusage.html`, for the three
    element names `euips_recommended` nominated for this ticket.
  - HL7 Europe `observation-travel-eu-eps`, for the travel code.

RESULT: **every LOINC section code is correct**, as is `Composition.type`
60591-5, the absent/unknown CodeSystem URL and all six absent codes.

Four disagreements were found, and none of them is a wrong section code:

  1. EPS makes 47519-4 and 46264-8 **1..1**; both are RECOMMENDED here.
     Codes agree, obligations do not — #906.
  2. EPS has **no** section for 11348-0. It is an IPS section.
     `EPS_TEXT_SECTIONS`'s note on 11329-0 had anticipated this ("once
     11348-0 is unprofiled") and #880 decided against moving resolved
     conditions into a free-text section. The fetch turns an expectation
     into a measurement.
  3. The three device element names are **all three wrong** against R5,
     exactly as the module suspected — #907.
  4. The travel-history Observation code was SNOMED `420008001`, chosen
     provisionally by #796. The EPS profile FIXES it to LOINC `94651-7`.
     Fixed here, with the old code kept in the MATCH set.

THE DISTINCTION THIS FILE EXISTS TO PIN: verified codes are not
conformance. The EPS guide is a ballot whose own pages say it is not an
authorized publication, it is an R4 guide while this platform is R5, and
cardinality was not checked. #799's rule is unchanged — "all required
sections present", never "EU-conformant".
"""
from __future__ import annotations

import pytest

from app.services import euips_header, euips_report, euips_sections as euips

#: Every section code, as published in `composition-eu-eps`.
EPS_PUBLISHED = {
    "11450-4": "1..1",   # sectionProblems
    "48765-2": "1..1",   # sectionAllergies
    "10160-0": "1..1",   # sectionMedications
    "47519-4": "1..1",   # sectionProceduresHx   <- RECOMMENDED here
    "46264-8": "1..1",   # sectionMedicalDevices <- RECOMMENDED here
    "11369-6": "0..1",   # sectionImmunizations
    "30954-2": "0..1",   # sectionResults
    "42348-3": "0..1",   # sectionAdvanceDirectives
    "104605-1": "0..1",  # sectionAlert
    "47420-5": "0..1",   # sectionFunctionalStatus
    "10162-6": "0..1",   # sectionPregnancyHx
    "81338-6": "0..1",   # sectionPatientStory
    "18776-5": "0..1",   # sectionPlanOfCare
    "29762-2": "0..1",   # sectionSocialHistory
    "8716-3": "0..1",    # sectionVitalSigns
    "10182-4": "0..1",   # sectionTravelHx
    "11329-0": "0..1",   # sectionPatientHx
}

#: Published in CodeSystem-absent-unknown-uv-ips v1.1.0.
PUBLISHED_ABSENT = {
    "no-known-allergies", "no-known-problems", "no-known-medications",
    "no-known-immunizations", "no-known-procedures", "no-known-devices",
}


class TestEverySectionCodeIsPublished:
    @pytest.mark.parametrize(
        "section", [s for s in euips.SECTIONS if s.loinc],
        ids=lambda s: s.key)
    def test_the_code_appears_in_the_published_guide(self, section):
        """Each code we use, found in what was fetched.

        `past_illnesses` is the one exception and it is deliberate: EPS has
        no 11348-0 section at all, so it is checked against IPS instead,
        below.
        """
        if section.key == "past_illnesses":
            pytest.skip("checked separately — EPS has no 11348-0 section")
        assert section.loinc in EPS_PUBLISHED, (
            f"{section.key} uses {section.loinc}, which is not a slice of "
            "composition-eu-eps as fetched 2026-11-02"
        )

    def test_the_eps_text_sections_are_published_too(self):
        for s in euips.EPS_TEXT_SECTIONS:
            assert s["loinc"] in EPS_PUBLISHED

    def test_the_composition_type_code_is_the_published_one(self):
        """60591-5, used by ips_generator. EPS fixes Composition.type to it."""
        import inspect
        from app.services import ips_generator
        assert "60591-5" in inspect.getsource(ips_generator)

    def test_past_illnesses_is_an_IPS_section_EPS_does_not_define(self):
        """Not an error, and worth pinning so nobody "fixes" it by deleting
        the section. #880 decided resolved conditions stay domestic with
        their coding rather than move into EPS's free-text 11329-0."""
        past = euips.BY_KEY["past_illnesses"]
        assert past.loinc == "11348-0"
        assert past.loinc not in EPS_PUBLISHED
        assert past.obligation == euips.OPTIONAL


class TestEveryAbsentCodeIsPublished:
    def test_the_codesystem_url_is_the_canonical_one(self):
        assert euips.ABSENT_UNKNOWN_SYSTEM == (
            "http://hl7.org/fhir/uv/ips/CodeSystem/absent-unknown-uv-ips")

    @pytest.mark.parametrize("key", sorted(
        s.key for s in euips.SECTIONS if s.absent_code))
    def test_the_absent_code_is_in_the_published_codesystem(self, key):
        assert euips.BY_KEY[key].absent_code in PUBLISHED_ABSENT

    def test_absent_coding_emits_the_published_system_and_code(self):
        cc = euips.absent_coding("allergies")
        assert cc["coding"][0]["system"] == euips.ABSENT_UNKNOWN_SYSTEM
        assert cc["coding"][0]["code"] in PUBLISHED_ABSENT


class TestTheTravelCodeWasWrongAndIsFixed:
    def test_the_written_code_is_the_one_the_profile_FIXES(self):
        assert euips.TRAVEL_CODE == "94651-7"
        assert euips.TRAVEL_CODE_SYSTEM == "http://loinc.org"

    def test_the_provisional_snomed_code_is_still_MATCHED(self):
        """#796's rows are already stored. Dropping the old code from the
        matcher would turn the section from PRESENT to MISSING for every
        patient generated before today — silently, since nothing asserts a
        patient's section count over time."""
        assert euips.TRAVEL_CODE_LEGACY == "420008001"
        assert euips.TRAVEL_CODES == {"94651-7", "420008001"}

    def test_a_stored_row_with_the_OLD_code_still_reads_as_travel(self):
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j
        old = Row("Observation", {
            "resourceType": "Observation",
            "category": [{"coding": [{"code": "social-history"}]}],
            "code": {"coding": [{"code": "420008001"}]}})
        assert euips.status_for_resources([old])["travel_history"] == \
            euips.PRESENT

    def test_a_new_row_with_the_VERIFIED_code_reads_as_travel(self):
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j
        new = Row("Observation", {
            "resourceType": "Observation",
            "category": [{"coding": [{"code": "social-history"}]}],
            "code": {"coding": [{"code": "94651-7"}]}})
        assert euips.status_for_resources([new])["travel_history"] == \
            euips.PRESENT

    def test_the_generator_writes_a_CODED_country_not_a_free_string(self):
        """The profile's binding on value[x] is REQUIRED (ISO 3166-1-2), and
        a required binding is the kind a validator refuses rather than warns
        about. `valueString: "Thailand"` satisfied nothing."""
        import random
        from app.services import euips_eu_additions as add
        rows = add._travel_history("Patient/x", random.Random(1))
        obs = rows[0]
        assert "valueString" not in obs
        cc = obs["valueCodeableConcept"]["coding"][0]
        assert cc["system"] == add.ISO_3166_SYSTEM
        assert len(cc["code"]) == 2 and cc["code"].isupper()
        assert obs["code"]["coding"][0]["code"] == "94651-7"


class TestTheRecord:
    """#885 asked for a record of WHICH guide was fetched and WHEN, not just
    a flag. A bare True is a weaker claim than the False it replaced."""

    def test_the_flag_is_flipped(self):
        assert euips.CODES_VERIFIED is True

    def test_the_record_names_the_date_and_both_guides(self):
        r = euips.CODES_VERIFIED_AGAINST
        assert r["verified_on"] == "2026-11-02"
        names = " ".join(g["name"] for g in r["guides"])
        assert "EPS" in names and "IPS" in names

    def test_the_record_says_the_eps_guide_is_NOT_authorized(self):
        eps = [g for g in euips.CODES_VERIFIED_AGAINST["guides"]
               if "EPS" in g["name"]][0]
        assert eps["authorized_publication"] is False
        assert "ballot" in eps["version"].lower()
        assert eps["fhir_version"] == "R4"

    def test_the_record_lists_the_divergences_it_found(self):
        d = " ".join(euips.CODES_VERIFIED_AGAINST["divergences"])
        assert "47519-4" in d and "46264-8" in d    # the obligations
        assert "11348-0" in d                       # the missing section
        assert "R4" in d and "R5" in d              # the version gap

    def test_the_record_states_what_it_does_NOT_cover(self):
        n = " ".join(euips.CODES_VERIFIED_AGAINST["not_covered"])
        assert "euips_header" in n
        assert "onformance" in n   # "conformance"/"Conformance"


class TestWhatMustStayUnverified:
    def test_the_header_module_flag_is_STILL_False(self):
        """Not an oversight. Its scope includes R5 element shapes, and the
        EPS guide is an R4 guide — an R4 document cannot verify an R5 shape,
        so fetching it harder would not lift this. One flag per module, so a
        verified module is not vouched for by an unverified one.
        """
        assert euips_header.CODES_VERIFIED is False

    def test_the_header_does_not_IMPORT_the_sections_flag(self):
        """They mirror each other by convention, not by import. A future
        edit that aliased one to the other would silently vouch for the
        header module the next time the sections flag moved.

        Asserted on the SOURCE, because the obvious version of this test —
        `header.CODES_VERIFIED is not sections.CODES_VERIFIED` — cannot
        tell aliasing from two booleans that merely differ: Python interns
        True and False, so that comparison only ever restated
        "their values differ", which the test above already covers.
        """
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(euips_header))

        # No import of the sections module, at any level.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("euips_sections" not in a.name
                           for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert "euips_sections" not in (node.module or "")
                assert all("euips_sections" not in a.name
                           for a in node.names)

        # And its flag is a literal, not an expression reading someone
        # else's. A substring test would not do: this module mentions
        # `euips_sections.CODES_VERIFIED_AGAINST` in a COMMENT explaining
        # why its own flag stays False, and an earlier version of this
        # test failed on exactly that.
        assigned = [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "CODES_VERIFIED"
                    for t in n.targets)
        ]
        assert len(assigned) == 1
        assert isinstance(assigned[0], ast.Constant)
        assert assigned[0].value is False

    def test_the_report_still_REFUSES_the_conformance_claim(self):
        d = euips_report.DISCLAIMER
        assert "NOT a claim of EU or EHDS" in d
        assert "not confirmed adopted" in d
        assert "ballot" in d

    def test_the_disclaimer_no_longer_says_the_codes_are_unverified(self):
        """The stale-status failure mode: #848's heading said "open" for
        eleven days after the work was done and sent a session to redo a
        finished rotation. A disclaimer nobody updated is the same thing."""
        assert "not yet verified" not in euips_report.DISCLAIMER
