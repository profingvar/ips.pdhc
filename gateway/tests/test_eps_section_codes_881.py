"""#881 — the two LOINC codes the EPS specification supplies.

`euips_sections.py` carried `CODES_VERIFIED = False` and left a section's LOINC
as `None` rather than invent one. Three sections had `None`; the EPS
specification (`docs/EPS_patientoversikt.docx` and
`EPS_sektioner_vokabularer.xlsx`, both 2026-10-30) supplies two of them.

**The win exists only because nothing was guessed.** A guessed value would have
had to be found and unpicked instead — the #810/#816 lesson in a different
costume, where numbers invented before they existed cost 51 and 58 corrections.

The third, `patient_provided`, stays `None` on purpose: EPS does not profile it
(#880 decided it is domestic, not exported). These tests are therefore as much
about what was NOT filled in as about what was.
"""
from __future__ import annotations

from app.services import euips_sections as euips

ALERTS_LOINC = "104605-1"
TRAVEL_LOINC = "10182-4"


class TestTheTwoCodesEpsSupplies:
    def test_alerts_carries_the_EPS_code(self):
        assert euips.BY_KEY["alerts"].loinc == ALERTS_LOINC

    def test_travel_history_carries_the_EPS_code(self):
        assert euips.BY_KEY["travel_history"].loinc == TRAVEL_LOINC

    def test_each_note_says_WHERE_the_value_came_from(self):
        """A code with no provenance is indistinguishable from a guess, which
        is the state this ticket exists to leave behind. If a future edit
        shortens these notes to just the code, this turns red."""
        for key in ("alerts", "travel_history"):
            note = euips.BY_KEY[key].note
            assert "EPS specification" in note, key
            assert "#881" in note, key
            assert "CODES_VERIFIED" in note, key


class TestWhatWasDeliberatelyNotFilled:
    def test_patient_provided_is_STILL_None(self):
        """The control. Without it, these tests would also pass for a change
        that filled every empty code to make the catalogue look complete."""
        assert euips.BY_KEY["patient_provided"].loinc is None

    def test_and_its_note_records_that_as_a_DECISION(self):
        note = euips.BY_KEY["patient_provided"].note
        assert "DELIBERATELY" in note
        assert "#880" in note
        assert "81338-6" in note and "11329-0" in note

    def test_patient_provided_is_the_ONLY_section_without_a_code(self):
        """Pins the count, so a section added later without a LOINC is caught
        here rather than silently omitted from a Composition."""
        missing = sorted(s.key for s in euips.SECTIONS if s.loinc is None)
        assert missing == ["patient_provided"], missing


class TestFillingACodeIsNotVerifyingIt:
    def test_CODES_VERIFIED_is_now_TRUE_AND_BACKED_BY_A_RECORD(self):
        """The source is a CI-build of a STU 1 Ballot — a draft of a draft.
        Only #885, after a fetch of the published IG, may flip this."""
        # #885 did the fetch, so the guard this test was written to be —
        # "do not flip the flag without doing the work" — now asserts the
        # OTHER half: that the flip is backed by a record naming what was
        # checked and when. A bare `is True` would be a weaker claim than
        # the `is False` it replaced.
        assert euips.CODES_VERIFIED is True
        rec = euips.CODES_VERIFIED_AGAINST
        assert rec["verified_on"] == "2026-11-02"
        assert len(rec["guides"]) == 2
        for g in rec["guides"]:
            assert g["url"].startswith("https://")
            assert g["version"]
            assert g["checked"]
        # The EPS guide is a BALLOT and must be recorded as unauthorised, or
        # "verified" overstates what was checked.
        eps = [g for g in rec["guides"] if "EPS" in g["name"]][0]
        assert eps["authorized_publication"] is False
        assert "ballot" in eps["version"].lower()
        # And what the flag does NOT cover must be stated, not implied.
        assert rec["not_covered"]
        assert any("euips_header" in n for n in rec["not_covered"])

    def test_the_section_code_is_not_the_RESOURCE_code(self):
        """`10182-4` is the Composition SECTION code; `TRAVEL_CODES` holds the
        SNOMED code on the Observation itself. They are different layers and a
        future reader conflating them would break the discriminator."""
        assert TRAVEL_LOINC not in euips.TRAVEL_CODES
        # #885 verified this against the EPS profile, which FIXES
        # Observation.code to LOINC 94651-7; #795's provisional SNOMED code
        # was a reasonable guess and wrong. It stays in the MATCH set so
        # rows stored before today keep reading as travel history.
        assert euips.TRAVEL_CODE == "94651-7"
        assert euips.TRAVEL_CODE_SYSTEM == "http://loinc.org"
        assert euips.TRAVEL_CODES == frozenset({"94651-7", "420008001"})
