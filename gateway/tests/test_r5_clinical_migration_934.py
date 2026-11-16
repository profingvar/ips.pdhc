"""#934 step 3 — stored MedicationStatement/Procedure rows to R5, as new versions."""
from __future__ import annotations

import uuid

import pytest

from app.models.fhir_resource import FhirResource
from app.services import euips_sections as euips
from app.services import r5_clinical_migration as mig

REAL_MED = {"text": "Metformin", "coding": [{"system": "http://www.whocc.no/atc", "code": "A10BA02"}]}


def _ms(status="active", med=None):
    return {"resourceType": "MedicationStatement", "status": status,
            "subject": {"reference": "Patient/p"}, "medication": med or REAL_MED}


class Row:
    def __init__(s, t, j):
        s.resource_type, s.resource_json = t, j


# ----------------------------------------------------------------- transformation

def test_the_production_shape_is_wrapped_and_the_status_mapped():
    new, ch = mig.migrate_resource_json("MedicationStatement", _ms())
    assert new["medication"] == {"concept": REAL_MED}
    assert new["status"] == "recorded"
    assert sorted(ch) == ["status:active->recorded", "wrap:medication->medication.concept"]


@pytest.mark.parametrize("st", ["entered-in-error", "draft", "recorded"])
def test_R5_statuses_are_kept(st):
    new, ch = mig.migrate_resource_json("MedicationStatement", _ms(st, {"concept": REAL_MED}))
    assert ch == [] and new["status"] == st


def test_R4_medicationCodeableConcept_and_Reference_are_renamed():
    a, _ = mig.migrate_resource_json("MedicationStatement",
                                     {"status": "recorded", "medicationCodeableConcept": REAL_MED})
    assert a == {"status": "recorded", "medication": {"concept": REAL_MED}}
    b, _ = mig.migrate_resource_json("MedicationStatement",
                                     {"status": "recorded", "medicationReference": {"reference": "Medication/m"}})
    assert b["medication"] == {"reference": {"reference": "Medication/m"}}


def test_a_stale_R4_element_never_overwrites_an_R5_one():
    new, ch = mig.migrate_resource_json("MedicationStatement", {
        "status": "recorded", "medication": {"concept": REAL_MED},
        "medicationCodeableConcept": {"text": "stale"}})
    assert new["medication"] == {"concept": REAL_MED} and ch == ["drop-stale:medicationCodeableConcept"]


def test_procedure_performed_becomes_occurrence():
    new, ch = mig.migrate_resource_json("Procedure", {"status": "completed", "performedDateTime": "2020-01-01"})
    assert new == {"status": "completed", "occurrenceDateTime": "2020-01-01"}
    assert ch == ["rename:performedDateTime->occurrenceDateTime"]


def test_procedure_stale_performed_never_overwrites_occurrence():
    new, _ = mig.migrate_resource_json("Procedure", {"occurrenceDateTime": "2021", "performedDateTime": "1999"})
    assert new == {"occurrenceDateTime": "2021"}


def test_a_clean_row_is_the_SAME_object_and_the_input_is_never_mutated():
    clean = _ms("recorded", {"concept": REAL_MED})
    assert mig.migrate_resource_json("MedicationStatement", clean)[0] is clean
    old = _ms(); snapshot = repr(old)
    mig.migrate_resource_json("MedicationStatement", old)
    assert repr(old) == snapshot


@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_odd_input_does_not_raise(bad):
    assert mig.migrate_resource_json("Procedure", bad) == (bad, [])


# ----------------------------------------------------------------- the property that matters

def test_no_known_medications_is_STILL_explicitly_absent():
    old = _ms("unknown", euips.absent_coding("medications"))
    assert euips.status_for_resources([Row("MedicationStatement", old)])["medications"] \
        == euips.EXPLICITLY_ABSENT, "precondition"
    new, ch = mig.migrate_resource_json("MedicationStatement", old)
    assert ch
    assert euips.status_for_resources([Row("MedicationStatement", new)])["medications"] \
        == euips.EXPLICITLY_ABSENT


def test_a_real_medication_still_counts_as_present():
    before = euips.status_for_resources([Row("MedicationStatement", _ms())])["medications"]
    new, _ = mig.migrate_resource_json("MedicationStatement", _ms())
    assert euips.status_for_resources([Row("MedicationStatement", new)])["medications"] == before


# ----------------------------------------------------------------- the CLI

class TestTheCli:
    @pytest.fixture
    def seeded(self, client, db):
        rows = [FhirResource(resource_type=t, resource_id=str(uuid.uuid4()), version_id=1,
                             status="active", patient_guid=uuid.uuid4(), resource_json=j)
                for t, j in [("MedicationStatement", _ms()),
                             ("Procedure", {"resourceType": "Procedure", "status": "completed",
                                            "performedDateTime": "2020-01-01"}),
                             ("MedicationStatement", _ms("recorded", {"concept": REAL_MED}))]]
        db.session.add_all(rows)
        db.session.commit()
        return rows

    def _run(self, client, *a):
        return client.application.test_cli_runner().invoke(args=["migrate-r5-clinical-elements", *a])

    def test_default_is_a_dry_run(self, client, db, seeded):
        res = self._run(client)
        assert "2 would change" in res.output and "dry run" in res.output
        assert db.session.query(FhirResource).filter_by(status="superseded").count() == 0

    def test_apply_writes_NEW_VERSIONS_and_keeps_the_R4_content(self, client, db, seeded):
        rid = seeded[0].resource_id
        res = self._run(client, "--apply", "--expect", "2")
        assert "wrote 2 new version(s)" in res.output, res.output
        db.session.expire_all()
        v = {r.version_id: r for r in db.session.query(FhirResource).filter_by(resource_id=rid)}
        assert v[1].status == "superseded" and v[1].resource_json["status"] == "active"
        assert v[2].status == "active" and v[2].resource_json["medication"] == {"concept": REAL_MED}
        assert v[2].patient_guid == v[1].patient_guid

    def test_expect_mismatch_aborts_and_writes_nothing(self, client, db, seeded):
        res = self._run(client, "--apply", "--expect", "99")
        assert res.exit_code != 0
        assert db.session.query(FhirResource).filter_by(status="superseded").count() == 0

    def test_a_second_apply_is_a_no_op(self, client, db, seeded):
        self._run(client, "--apply")
        assert "0 would change" in self._run(client, "--apply").output
