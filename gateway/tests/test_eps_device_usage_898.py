"""#898 — the service declares R5 and was writing an R4 resource name.

R5 renamed `DeviceUseStatement` to **`DeviceUsage`**. This repo emitted the R4
spelling at `euips_recommended.py` and catalogued it in `euips_sections.py`,
while `fhir_routes.py` declares `fhirVersion: "5.0.0"`. So the R5 claim was,
in this one respect, false — and that matters more now that #877 chose to
EXPORT R5 rather than render R4: the export's correctness rests entirely on the
stored shapes being R5.

**Write the new name, read both.** `fhir_resources.resource_type` is a plain
`String(64)`, so rows keep whatever string was written. The production count of
old rows was unavailable when this landed (a production read was not
permitted), so nothing was migrated blind: the old spelling is accepted on READ
via `LEGACY_RESOURCE_TYPES` and never produced on WRITE.

The alias is deliberately NOT in `Section.resource_types`, because that tuple
is served over the API (`/patients/<guid>/euips-status`) and therefore tells a
producer what to write. An alias published there is an invitation to keep using
it.
"""
from __future__ import annotations

import random

from app.services import euips_recommended as rec
from app.services import euips_sections as euips

LEGACY = "DeviceUseStatement"
CANONICAL = "DeviceUsage"


class Row:
    def __init__(self, t, j):
        self.resource_type, self.resource_json = t, j


def _device_bodies():
    return rec._devices("Patient/p", None, random.Random(7))


class TestTheWritePathEmitsTheR5Name:
    def test_the_builder_produces_DeviceUsage(self):
        types = {b.get("resourceType") for b in _device_bodies()}
        assert CANONICAL in types, types

    def test_the_builder_NEVER_produces_the_R4_name(self):
        """The defect this ticket exists for."""
        for b in _device_bodies():
            assert b.get("resourceType") != LEGACY, b

    def test_no_write_path_anywhere_still_emits_it(self):
        """Belt and braces across the generator: a second builder added later
        with the old spelling would be caught here, not at an export."""
        rng = random.Random(3)
        bodies = rec.recommended_sections_for("Patient/p", "1980-01-01", rng=rng)
        assert all(b.get("resourceType") != LEGACY for b in bodies)


class TestTheCatalogueAdvertisesCanonicalNamesOnly:
    def test_resource_types_is_canonical(self):
        assert euips.BY_KEY["devices"].resource_types == ("Device", CANONICAL)

    def test_the_legacy_name_is_NOT_in_the_advertised_tuple(self):
        """`resource_types` is serialised into the euips-status response, so it
        describes what to WRITE. Publishing the alias there would invite
        producers to keep sending it."""
        for s in euips.SECTIONS:
            assert LEGACY not in s.resource_types, s.key

    def test_the_stale_note_is_gone(self):
        """The old note claimed no Device type existed at all. It had been
        wrong since 2026-10-07 and was quoted into an assessment as fact."""
        note = euips.BY_KEY["devices"].note
        assert "THE MISSING ONE" not in note
        assert "#898" in note


class TestTheReadPathAcceptsBoth:
    def test_a_row_with_the_LEGACY_name_still_matches_the_section(self):
        body = {"resourceType": LEGACY, "subject": {"reference": "Patient/p"}}
        assert euips.section_matches(euips.BY_KEY["devices"], LEGACY, body)

    def test_a_row_with_the_CANONICAL_name_matches(self):
        body = {"resourceType": CANONICAL, "subject": {"reference": "Patient/p"}}
        assert euips.section_matches(euips.BY_KEY["devices"], CANONICAL, body)

    def test_a_patient_whose_ONLY_device_row_is_legacy_reads_PRESENT(self):
        """The end-to-end point of accept-both: an un-migrated row must not
        make a RECOMMENDED section read MISSING, which under EPS (1..1) would
        become a conformance failure."""
        rows = [Row(LEGACY, {"resourceType": LEGACY,
                             "subject": {"reference": "Patient/p"}})]
        status = euips.status_for_resources(rows)
        assert status["devices"] == euips.PRESENT, status["devices"]

    def test_an_UNRELATED_type_is_still_not_matched(self):
        """The control. Without it, a matcher that returned True for everything
        would pass every test above."""
        body = {"resourceType": "Observation"}
        assert not euips.section_matches(euips.BY_KEY["devices"],
                                         "Observation", body)


class TestTheAliasItself:
    def test_it_maps_legacy_to_canonical(self):
        assert euips.canonical_resource_type(LEGACY) == CANONICAL

    def test_it_is_ONE_WAY(self):
        """The canonical name must never be rewritten to the legacy one, or
        the write path would be dragged backwards by the read path."""
        assert euips.canonical_resource_type(CANONICAL) == CANONICAL

    def test_an_unknown_type_passes_through_unchanged(self):
        assert euips.canonical_resource_type("Observation") == "Observation"

    def test_there_is_exactly_ONE_alias(self):
        """Pins the size, so adding a second is a deliberate act with its own
        removal condition rather than a habit."""
        assert euips.LEGACY_RESOURCE_TYPES == {LEGACY: CANONICAL}
