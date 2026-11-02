"""#886 (EPS B6) — alert.pdhc's implant selection as FHIR, not a generator.

EPS makes section 46264-8 **1..1**, and `Förekomst av implantat` is that list
as real clinician-selected data. `alert_assertion` already carries everything
needed: `code_system`, `code`, `national_term`, `asserted_at`, `negation`,
`provenance`.

**There is no HTTP client, deliberately.** alert.pdhc runs nowhere — measured:
no container locally, none on miserver, no deploy directory, no row in
CLAUDE.md's service table. A client against it would reproduce the xlate defect
(#833), where a module-level default URL made "nobody wired this up"
indistinguishable from "it blipped". So the transformation is built and proven,
and the transport is not invented.

The three tests that carry the most are:

  - `test_the_national_term_survives` — twelve codes in this selection bind
    two or three terms, so the code alone cannot say what the clinician picked.
  - `test_the_timing_is_asserted_at_not_recorded_at` — using the record time
    would date every implant to the day it was imported.
  - `test_a_negated_assertion_makes_the_section_EXPLICITLY_ABSENT` — the whole
    point: a mandatory section filled correctly when the patient has no
    implant, rather than reading MISSING.
"""
from __future__ import annotations

import uuid

import pytest

from app.services import alert_implants as ai
from app.services import euips_sections as euips
from app.services.fhir_service import SUPPORTED_RESOURCE_TYPES

PATIENT_REF = "Patient/11111111-1111-1111-1111-111111111111"
ASSERTED = "2024-03-15T09:00:00+00:00"
RECORDED = "2026-11-02T08:00:00+00:00"

#: Shaped like an `alert_assertion` row. `Z95.0` is used because alert's own
#: code records that it binds THREE national terms in this selection, which is
#: what makes `national_term` load-bearing rather than decorative.
def _assertion(**over):
    a = {
        "patient_guid": "11111111-1111-1111-1111-111111111111",
        "subgroup": ai.IMPLANT_SUBGROUP,
        "code_system": "urn:oid:1.2.752.116.1.1.1.1.3",
        "code": "Z95.0",
        "national_term": "Förekomst av pacemaker",
        "asserted_at": ASSERTED,
        "recorded_at": RECORDED,
        "negation": False,
        "provenance": "documented",
    }
    a.update(over)
    return a


class Row:
    def __init__(self, t, j):
        self.resource_type, self.resource_json = t, j


class TestThePresentCase:
    def test_it_produces_a_Device_and_a_DeviceUsage(self):
        out = ai.to_fhir(_assertion(), patient_ref=PATIENT_REF,
                         device_id="d1", usage_id="u1")
        assert [r["resourceType"] for r in out] == ["Device", "DeviceUsage"]
        assert out[1]["device"]["reference"] == "Device/d1"

    def test_the_coding_carries_system_and_code(self):
        d = ai.to_fhir(_assertion(), patient_ref=PATIENT_REF)[0]
        c = d["type"]["coding"][0]
        assert c["code"] == "Z95.0"
        assert c["system"].startswith("urn:oid:")

    def test_the_national_term_survives(self):
        """alert's own registration.py: "Twelve codes bind two or three …
        `Z95.0` covers ICD, pacemaker AND pacemaker electrode … a record
        holding only the code cannot say what the clinician picked."

        So dropping `national_term` is a clinical loss, not a formatting one.
        It goes in `CodeableConcept.text`, which FHIR defines as the
        representation the USER selected."""
        d = ai.to_fhir(_assertion(), patient_ref=PATIENT_REF)[0]
        assert d["type"]["text"] == "Förekomst av pacemaker"
        assert "Förekomst av pacemaker" in d["text"]["div"]

    def test_two_assertions_sharing_a_CODE_stay_distinguishable(self):
        """The failure mode the test above prevents, made explicit: the same
        Z95.0 with two different terms must not collapse into one thing."""
        a = ai.to_fhir(_assertion(national_term="Förekomst av pacemaker"),
                       patient_ref=PATIENT_REF)[0]
        b = ai.to_fhir(_assertion(national_term="Förekomst av ICD"),
                       patient_ref=PATIENT_REF)[0]
        assert a["type"]["coding"] == b["type"]["coding"]
        assert a["type"]["text"] != b["type"]["text"]

    def test_the_timing_is_asserted_at_not_recorded_at(self):
        """alert keeps the two apart for the same reason #895 does. A
        DeviceUsage timing is a clinical fact about the patient, so it takes
        the asserted time; `recorded_at` would date every implant to the day
        it was imported."""
        u = ai.to_fhir(_assertion(), patient_ref=PATIENT_REF)[1]
        assert u["timingDateTime"] == ASSERTED
        assert u["timingDateTime"] != RECORDED


class TestTheNegatedCase:
    def test_it_produces_the_ABSENT_assertion_and_no_DeviceUsage(self):
        """`negation` means it has been ESTABLISHED that the patient does not
        have it. A Device carrying a flag would make every consumer that reads
        the section see an implant that is not there."""
        out = ai.to_fhir(_assertion(negation=True), patient_ref=PATIENT_REF)
        assert len(out) == 1
        assert out[0]["resourceType"] == "Device"
        assert out[0]["type"] == euips.absent_coding("devices")

    def test_a_negated_assertion_makes_the_section_EXPLICITLY_ABSENT(self):
        """The point of the whole ticket: a MANDATORY section (1..1 under EPS)
        filled correctly for a patient who has no implant — rather than reading
        MISSING, which under 1..1 is a conformance failure."""
        out = ai.to_fhir(_assertion(negation=True), patient_ref=PATIENT_REF)
        status = euips.status_for_resources([Row("Device", out[0])])
        assert status["devices"] == euips.EXPLICITLY_ABSENT, status["devices"]

    def test_a_PRESENT_assertion_makes_it_PRESENT(self):
        """The control: without it, the test above would also pass for a
        mapping that always produced the absent code."""
        out = ai.to_fhir(_assertion(), patient_ref=PATIENT_REF, device_id="d1")
        rows = [Row(r["resourceType"], r) for r in out]
        status = euips.status_for_resources(rows)
        assert status["devices"] == euips.PRESENT, status["devices"]


class TestSimulatedStaysDistinguishable:
    def test_a_simulated_assertion_is_marked_as_such(self):
        """The MDR-relevant surface. `euips_sections`'s own note on the alerts
        section says a SIMULATED alert must stay distinguishable from a
        computed one; the same holds for an implant."""
        for r in ai.to_fhir(_assertion(provenance="simulated"),
                            patient_ref=PATIENT_REF):
            tag = r["meta"]["tag"][0]
            assert tag["code"] == "simulated"
            assert "SIMULATED" in tag["display"]

    def test_a_documented_assertion_is_marked_differently(self):
        for r in ai.to_fhir(_assertion(), patient_ref=PATIENT_REF):
            tag = r["meta"]["tag"][0]
            assert tag["code"] == "documented"
            assert "SIMULATED" not in tag["display"]

    def test_the_marker_survives_the_NEGATED_path_too(self):
        """The path with fewer resources is the one a marker is most easily
        dropped from."""
        out = ai.to_fhir(_assertion(negation=True, provenance="simulated"),
                         patient_ref=PATIENT_REF)
        assert out[0]["meta"]["tag"][0]["code"] == "simulated"


class TestTheContract:
    def test_a_non_implant_subgroup_is_refused_by_name(self):
        with pytest.raises(ValueError) as e:
            ai.to_fhir(_assertion(subgroup="Something else"),
                       patient_ref=PATIENT_REF)
        assert "not an implant assertion" in str(e.value)

    def test_is_implant_matches_on_the_SELECTION_not_the_code(self):
        """An ICD-10-SE Z95.x code can be reached from more than one
        selection, and the selection is what the clinician picked from."""
        assert ai.is_implant(_assertion()) is True
        assert ai.is_implant(_assertion(subgroup="Annat")) is False

    def test_a_missing_field_is_NAMED_not_a_KeyError(self):
        a = _assertion()
        del a["national_term"]
        assert ai.missing_contract_fields(a) == ["national_term"]
        with pytest.raises(ValueError) as e:
            ai.to_fhir(a, patient_ref=PATIENT_REF)
        assert "national_term" in str(e.value)

    def test_the_contract_matches_what_alert_actually_stores(self):
        """Pins the field names against alert's own column names. If alert
        renames one, this is where it is noticed rather than at an import."""
        assert set(ai.ASSERTION_CONTRACT) == {
            "patient_guid", "subgroup", "code_system", "code",
            "national_term", "asserted_at", "negation", "provenance"}


class TestItTargetsWhatB3MadeVisible:
    def test_both_types_are_API_supported(self):
        """#883 added these to SUPPORTED_RESOURCE_TYPES, and #898 fixed the
        spelling. If either regressed, these resources could be built and not
        stored."""
        for rt in ("Device", "DeviceUsage"):
            assert rt in SUPPORTED_RESOURCE_TYPES

    def test_it_never_emits_the_R4_resource_name(self):
        for r in ai.to_fhir(_assertion(), patient_ref=PATIENT_REF):
            assert r["resourceType"] != "DeviceUseStatement"

    def test_the_output_round_trips_through_the_FHIR_API(self, client, db):
        """End to end: building a resource the API refuses would be a mapping
        nobody can use."""
        p = client.post("/fhir/Patient", json={
            "resourceType": "Patient",
            "name": [{"family": "Implantatsson"}],
            "gender": "other", "birthDate": "1960-01-01"})
        assert p.status_code == 201, p.get_data(as_text=True)
        pid = p.get_json()["id"]
        out = ai.to_fhir(_assertion(), patient_ref=f"Patient/{pid}",
                         device_id=str(uuid.uuid4()),
                         usage_id=str(uuid.uuid4()))
        for r in out:
            resp = client.post(f"/fhir/{r['resourceType']}", json=r)
            assert resp.status_code == 201, \
                f"{r['resourceType']} refused: {resp.get_data(as_text=True)}"
