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
    def test_CODES_VERIFIED_is_still_False(self):
        """The source is a CI-build of a STU 1 Ballot — a draft of a draft.
        Only #885, after a fetch of the published IG, may flip this."""
        assert euips.CODES_VERIFIED is False

    def test_the_section_code_is_not_the_RESOURCE_code(self):
        """`10182-4` is the Composition SECTION code; `TRAVEL_CODES` holds the
        SNOMED code on the Observation itself. They are different layers and a
        future reader conflating them would break the discriminator."""
        assert TRAVEL_LOINC not in euips.TRAVEL_CODES
        assert euips.TRAVEL_CODES == frozenset({"420008001"})
