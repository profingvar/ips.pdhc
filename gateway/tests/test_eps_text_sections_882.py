"""#882 (EPS B2) — two free-text sections EPS defines and this service lacks.

    81338-6   Patient Story / Patientens berättelse
    11329-0   Patient History / Sjukdomshistoria   (EPS-unique)

**They are deliberately NOT in `SECTIONS`.** That tuple drives the
resource-derived report, and `status_for_resources` answers PRESENT /
EXPLICITLY_ABSENT / MISSING from the rows a patient actually has. Neither
answer is true for a section no resource backs:

  - MISSING reads as "this patient lacks it", when the truth is "this service
    does not carry this section at all". Every patient would show two
    permanent MISSING rows, which is how a coverage report trains its reader
    to skim past it.
  - A fourth status would have to be handled by four consumers, and one breaks
    SILENTLY: `euips_report` detects a patient with nothing at all via
    `all(v == MISSING for v in st.values())`, and a status that is never
    MISSING makes that permanently false.

So they are declared in `EPS_TEXT_SECTIONS` and surfaced separately, which
says something more useful than a status: DECLARED and NOT CARRIED.

Content generation waits on a document builder — the euIPS path assembles no
Composition today, so narrative has nowhere to live until #896 (EPS B7). The
`Composition` with `"section"` in `ips_generator.py` belongs to the older
IPS-card path, and `euips_header.composition_header()` builds the header only.
"""
from __future__ import annotations

import uuid

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_report, euips_sections as euips

STORY = "81338-6"
HISTORY = "11329-0"


class TestTheTwoSectionsAreDeclared:
    def test_both_codes_are_present_with_their_titles(self):
        by_code = {s["loinc"]: s for s in euips.EPS_TEXT_SECTIONS}
        assert by_code[STORY]["title"] == "Patient Story"
        assert by_code[STORY]["title_sv"] == "Patientens berättelse"
        assert by_code[HISTORY]["title"] == "Patient History"
        assert by_code[HISTORY]["title_sv"] == "Sjukdomshistoria"

    def test_patient_history_is_marked_EPS_UNIQUE_and_patient_story_is_not(self):
        """IPS has no Patient History counterpart. Recording which of the two
        is EPS-only is what tells a reader whether an IPS consumer will
        understand it."""
        by_code = {s["loinc"]: s for s in euips.EPS_TEXT_SECTIONS}
        assert by_code[HISTORY]["eps_unique"] is True
        assert by_code[STORY]["eps_unique"] is False

    def test_each_note_records_the_880_decision_it_depends_on(self):
        """Both notes exist to stop a later reader "simplifying" these into an
        existing section. The reasons are the load-bearing part."""
        by_code = {s["loinc"]: s for s in euips.EPS_TEXT_SECTIONS}
        assert "patient_provided" in by_code[STORY]["note"]
        assert "#880" in by_code[STORY]["note"]
        assert "11348-0" in by_code[HISTORY]["note"]
        assert "clinicalStatus" in by_code[HISTORY]["note"]


class TestTheResourceDerivedCatalogueIsUNTOUCHED:
    def test_SECTIONS_is_still_seventeen(self):
        """The control on the whole design. If these two ever get added to
        SECTIONS, this turns red and whoever did it has to read why not."""
        assert len(euips.SECTIONS) == 17

    def test_neither_code_appears_in_SECTIONS(self):
        codes = {s.loinc for s in euips.SECTIONS}
        assert STORY not in codes
        assert HISTORY not in codes

    def test_there_are_still_exactly_THREE_statuses(self):
        """A fourth would need four consumers updated, one of which fails
        silently — see the module docstring."""
        assert {euips.PRESENT, euips.EXPLICITLY_ABSENT, euips.MISSING} == {
            "PRESENT", "EXPLICITLY_ABSENT", "MISSING"}

    def test_status_for_resources_still_answers_for_every_SECTION_and_no_more(self):
        """Pins the shape four consumers index into. An extra key here is a
        KeyError in `euips_report`'s matrix; a missing one is worse."""
        status = euips.status_for_resources([])
        assert set(status) == {s.key for s in euips.SECTIONS}


class TestTheGapIsVISIBLE:
    def test_the_euips_status_endpoint_reports_them(self, client, db):
        fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                            resource_json={"resourceType": "Patient"})
        db.session.add(fhir)
        db.session.flush()
        p = PatientIndex(fhir_resource_guid=fhir.guid,
                         resource_id=str(uuid.uuid4()), family_name="Berättelsson")
        db.session.add(p)
        db.session.commit()
        body = client.get(f"/api/v1/patients/{p.guid}/euips-sections").get_json()
        declared = body["eps_sections_declared_not_carried"]
        assert {d["loinc"] for d in declared} == {STORY, HISTORY}
        # And they are NOT among the per-patient section statuses.
        assert all(s.get("loinc") != STORY for s in body["sections"])

    def test_the_report_dict_carries_them(self, client, db):
        r = euips_report.report()
        assert {s["loinc"] for s in r["eps_sections_declared_not_carried"]} == {
            STORY, HISTORY}

    def test_the_rendered_report_SAYS_they_are_not_per_patient(self, client, db):
        """A declaration no surface prints is no better than no declaration —
        and the wording has to stop a reader counting it as a patient gap."""
        txt = euips_report.format_report(euips_report.report())
        assert "declared by EPS, NOT carried here" in txt
        assert STORY in txt and HISTORY in txt
        assert "not per-patient" in txt

    def test_the_report_still_renders_without_the_key(self, client, db):
        """Defensive: `format_report` is given a dict, and an older caller or a
        cached payload may not have the key. It must not raise."""
        r = euips_report.report()
        del r["eps_sections_declared_not_carried"]
        txt = euips_report.format_report(r)
        assert "declared by EPS" not in txt
