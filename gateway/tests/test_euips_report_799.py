"""#799 — the euIPS completeness report, and the two things it must not say.

1. It must **not** claim regulatory conformance. The source document states
   the EHDS implementing acts were not confirmed adopted as of October 2026,
   and `CODES_VERIFIED` is False. A tool that prints "EU-conformant" against a
   specification that is not finally adopted is worse than one that prints
   "all required sections present", because the first is a claim someone may
   repeat in a technical file.
2. It must **not** report a MISSING recommended or optional section as a
   failure. #794 established that those may legitimately be absent and that
   the generator produces that outcome on purpose; calling it a failure would
   make a correct cohort look broken and train the reader to ignore the output.
"""
from __future__ import annotations

import uuid

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_report, euips_required
from app.services import euips_sections as euips


def _clinic(db):
    c = Clinic(name="Report Clinic", organisation_guid="org-rep-0001",
               identifier="org-rep-0001", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _bare_patient(db, name="Empty"):
    """A patient with no clinical content at all -- the live state of 110 of
    150 production patients."""
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     family_name=name)
    db.session.add(p)
    db.session.commit()
    res.patient_guid = p.guid
    db.session.commit()
    return p


def _add_required(db, patient, absent_only=True):
    for body in euips_required.required_sections_for(
            f"Patient/{patient.resource_id}", absent_only=absent_only):
        r = FhirResource(resource_type=body["resourceType"],
                         resource_id=body["id"], resource_json=body,
                         patient_guid=patient.guid)
        db.session.add(r)
    db.session.commit()


class TestWhatItRefusesToClaim:
    def test_it_never_says_eu_conformant(self, client, db):
        _bare_patient(db)
        text = euips_report.format_report(euips_report.report())
        lowered = text.lower()
        assert "eu-conformant" not in lowered
        assert "ehds-conformant" not in lowered
        assert "all required sections present" in lowered

    def test_the_disclaimer_is_in_every_output(self, client, db):
        _bare_patient(db)
        r = euips_report.report()
        assert "NOT a claim of EU or EHDS conformance" in r["disclaimer"]
        assert "NOT a claim of EU or EHDS conformance" in \
            euips_report.format_report(r)

    def test_it_reports_that_the_codes_are_unverified(self, client, db):
        _bare_patient(db)
        r = euips_report.report()
        assert r["codes_verified"] is False
        assert "codes verified against the published IG: False" in \
            euips_report.format_report(r)

    def test_the_disclaimer_names_both_reasons(self, client, db):
        """Two independent reasons, and conflating them would understate it:
        the acts are not adopted AND the codes are unverified."""
        d = euips_report.DISCLAIMER
        assert "not confirmed adopted" in d
        assert "not yet verified" in d


class TestOnlyRequiredSectionsFail:
    def test_a_patient_with_only_absent_assertions_is_conformant(self, client, db):
        """Nothing to report is a VALID summary, provided each required
        section says so explicitly."""
        p = _bare_patient(db)
        _add_required(db, p, absent_only=True)
        r = euips_report.report()
        assert r["conformant"] == 1
        assert r["not_conformant"] == 0
        assert r["failures"] == []

    def test_missing_recommended_sections_are_not_failures(self, client, db):
        """#794's conclusion, enforced here. A conformant patient with no
        immunisations, procedures or devices must NOT appear in failures."""
        p = _bare_patient(db)
        _add_required(db, p, absent_only=True)
        r = euips_report.report()
        rec = r["by_obligation"][euips.RECOMMENDED]
        assert rec["immunisations"][euips.MISSING] == 1
        assert rec["devices"][euips.MISSING] == 1
        assert r["failures"] == [], "a missing recommended section was failed"
        assert r["conformant"] == 1

    def test_a_missing_required_section_IS_a_failure(self, client, db):
        p = _bare_patient(db, name="NoRequired")
        r = euips_report.report()
        assert r["conformant"] == 0
        assert r["not_conformant"] == 1
        assert len(r["failures"]) == 1
        assert set(r["failures"][0]["missing_required"]) == set(euips.REQUIRED_KEYS)

    def test_the_failure_names_WHICH_required_section_is_missing(self, client, db):
        """"Which header is missing" is the question the ticket asks."""
        p = _bare_patient(db)
        # Allergies and medications only; no problem list.
        for key, rtype in (("allergies", "AllergyIntolerance"),
                           ("medications", "MedicationStatement")):
            body = {"resourceType": rtype, "id": str(uuid.uuid4()),
                    ("medication" if rtype == "MedicationStatement" else "code"):
                        euips.absent_coding(key)}
            _db.session.add(FhirResource(resource_type=rtype,
                                         resource_id=body["id"],
                                         resource_json=body,
                                         patient_guid=p.guid))
        _db.session.commit()
        r = euips_report.report()
        assert r["failures"][0]["missing_required"] == ["problems"]


class TestTheBaseline:
    def test_it_counts_patients_with_no_content_at_all(self, client, db):
        """110 of 150 live patients are in this state, and it is worth its own
        number: "no statement whatsoever" is a different problem from "missing
        one section"."""
        _bare_patient(db, name="A")
        _bare_patient(db, name="B")
        p = _bare_patient(db, name="C")
        _add_required(db, p, absent_only=True)
        r = euips_report.report()
        assert r["patients"] == 3
        assert r["no_content_in_any_section"] == 2
        assert r["conformant"] == 1

    def test_every_section_appears_under_its_obligation_level(self, client, db):
        _bare_patient(db)
        r = euips_report.report()
        counted = sum(len(v) for v in r["by_obligation"].values())
        assert counted == len(euips.SECTIONS)
        assert set(r["by_obligation"][euips.REQUIRED]) == set(euips.REQUIRED_KEYS)

    def test_the_failure_list_is_capped_and_says_how_many_more(self, client, db):
        for i in range(14):
            _bare_patient(db, name=f"P{i}")
        r = euips_report.report(failure_limit=10)
        assert len(r["failures"]) == 10
        assert r["failures_truncated"] == 4
        assert "and 4 more" in euips_report.format_report(r)


class TestPerBatch:
    def test_a_batch_report_covers_only_that_batch(self, client, db):
        """#797 needs this to say 100/100 rather than leaving it inferred."""
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "6"},
                    follow_redirects=True)
        batch = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        _bare_patient(db, name="NotInTheBatch")

        whole = euips_report.report()
        just = euips_report.report(batch)
        assert whole["patients"] == 7
        assert just["patients"] == 6
        assert just["conformant"] == 6
        assert just["failures"] == []
        assert "batch" in just["scope"]

    def test_an_unknown_batch_reports_zero_rather_than_failing(self, client, db):
        r = euips_report.report(str(uuid.uuid4()))
        assert r["patients"] == 0
        assert r["conformant"] == 0
        assert r["failures"] == []


class TestTheCli:
    def test_the_report_command_runs(self, app, db):
        p = _bare_patient(db)
        _add_required(db, p, absent_only=True)
        res = app.test_cli_runner().invoke(args=["euips-report"])
        assert res.exit_code == 0, res.output
        assert "euIPS section coverage" in res.output
        assert "NOT a claim of EU or EHDS conformance" in res.output
        # The obligation levels must be labelled with what MISSING means.
        assert "a MISSING section here is a FAILURE" in res.output
        assert "MISSING is permitted, not a failure" in res.output

    def test_the_batch_command_handles_an_unknown_batch(self, app, db):
        res = app.test_cli_runner().invoke(
            args=["euips-report-batch", str(uuid.uuid4())])
        assert res.exit_code == 0, res.output
        assert "No patients in batch" in res.output
