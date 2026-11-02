"""#908 — bring STORED Device/DeviceUsage rows to the R5 element names.

#907 fixed what this service writes. Rows written before it still carry
the old shapes, and #896's export deep-copies `resource_json`, so an
export of an old row still ships an element R5 does not define.

#908 drafted this as JSONB statements. They were correct and
Postgres-only, which meant the transformation could not be exercised by a
suite that runs on SQLite — and the change that worries me most is a
RENAME, where a wrong operator silently drops a patient reference. So the
transformation is a pure function and the CLI walks rows over it: one
implementation, both databases, a test per case.

THE TWO THINGS THAT COULD GO WRONG, and what they would cost:

  - **Dropping `Device.code` instead of renaming it.** On an absent
    assertion that coding IS the section's EXPLICITLY_ABSENT signal.
    Deleting it turns "no known devices" into "nothing recorded" — the
    exact silent downgrade `_CODE_BEARING_FIELDS`' own comment warns
    about, and invisible afterwards because both states are plausible.
  - **Letting a stale `subject` overwrite a valid `patient`.** That files
    one patient's resource under whoever the stale field names.

Both have tests that fail if the direction is reversed.

NOTE ON WHEN TO RUN IT. #908's recommendation is to leave the data alone
while the Device rows are synthetic, and to migrate before real implant
data arrives (#905). The command is therefore DRY RUN BY DEFAULT and
takes `--expect`, so the operator runs it dry, reads the count, and
re-runs with that count — a table that changed underneath them aborts
rather than being edited blind (#829).
"""
from __future__ import annotations

import uuid

import pytest

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_sections as euips
from app.services import r5_device_migration as mig

PATIENT_REF = "Patient/abc"
OTHER_REF = "Patient/someone-else"


class TestTheTransformation:
    def test_device_patient_is_DELETED(self):
        before = {"resourceType": "Device", "status": "active",
                  "patient": {"reference": PATIENT_REF},
                  "type": {"coding": [{"code": "x"}]}}
        after, changes = mig.migrate_resource_json("Device", before)
        assert "patient" not in after
        assert changes == ["drop:patient"]
        # everything else survives
        assert after["type"] == before["type"]
        assert after["status"] == "active"

    def test_device_code_is_RENAMED_to_type_not_deleted(self):
        """That coding is a section's EXPLICITLY_ABSENT signal. Deleting it
        would turn "no known devices" into "nothing recorded"."""
        absent = euips.absent_coding("devices")
        before = {"resourceType": "Device", "status": "unknown",
                  "code": absent}
        after, changes = mig.migrate_resource_json("Device", before)
        assert "code" not in after
        assert after["type"] == absent, "the coding must survive the rename"
        assert changes == ["rename:code->type"]

    def test_deviceusage_subject_is_RENAMED_to_patient(self):
        before = {"resourceType": "DeviceUsage", "status": "active",
                  "subject": {"reference": PATIENT_REF}}
        after, changes = mig.migrate_resource_json("DeviceUsage", before)
        assert "subject" not in after
        assert after["patient"] == {"reference": PATIENT_REF}, \
            "the patient reference must survive the rename"
        assert changes == ["rename:subject->patient"]

    def test_both_changes_on_one_device(self):
        before = {"resourceType": "Device",
                  "patient": {"reference": PATIENT_REF},
                  "code": {"coding": [{"code": "no-known-devices"}]}}
        after, changes = mig.migrate_resource_json("Device", before)
        assert set(after) == {"resourceType", "type"}
        assert sorted(changes) == ["drop:patient", "rename:code->type"]


class TestTheStaleNameNeverWins:
    def test_a_stale_subject_does_NOT_overwrite_a_valid_patient(self):
        """The dangerous direction. Reversed, this files one patient's
        resource under whoever the stale field names."""
        before = {"resourceType": "DeviceUsage",
                  "patient": {"reference": PATIENT_REF},   # R5, correct
                  "subject": {"reference": OTHER_REF}}     # stale
        after, changes = mig.migrate_resource_json("DeviceUsage", before)
        assert after["patient"] == {"reference": PATIENT_REF}
        assert "subject" not in after
        assert changes == ["drop-stale:subject"]

    def test_a_stale_code_does_NOT_overwrite_an_existing_type(self):
        real = {"coding": [{"code": "real-implant"}]}
        before = {"resourceType": "Device", "type": real,
                  "code": {"coding": [{"code": "stale"}]}}
        after, changes = mig.migrate_resource_json("Device", before)
        assert after["type"] == real
        assert "code" not in after
        assert changes == ["drop-stale:code"]


class TestItIsSafeAndIdempotent:
    def test_a_clean_row_is_returned_UNCHANGED_and_IDENTICAL(self):
        """Identity, not equality: a caller tests it to avoid a pointless
        write, and an equal-but-new dict would defeat that."""
        clean = {"resourceType": "Device", "status": "active",
                 "type": {"coding": [{"code": "x"}]}}
        after, changes = mig.migrate_resource_json("Device", clean)
        assert changes == []
        assert after is clean

    def test_a_second_run_changes_nothing(self):
        before = {"resourceType": "DeviceUsage",
                  "subject": {"reference": PATIENT_REF}}
        once, c1 = mig.migrate_resource_json("DeviceUsage", before)
        twice, c2 = mig.migrate_resource_json("DeviceUsage", once)
        assert c1 and c2 == []
        assert twice is once

    def test_it_does_not_mutate_the_input(self):
        """A migration that edits in place makes a dry run impossible."""
        before = {"resourceType": "Device",
                  "patient": {"reference": PATIENT_REF}}
        mig.migrate_resource_json("Device", before)
        assert "patient" in before

    @pytest.mark.parametrize("rtype", ["Observation", "Patient", "Procedure",
                                       "Immunization", ""])
    def test_an_unhandled_resource_type_is_untouched(self, rtype):
        """Observation and Procedure legitimately HAVE `subject`. Touching
        them would be the worst possible overreach."""
        before = {"resourceType": rtype,
                  "subject": {"reference": PATIENT_REF},
                  "code": {"coding": [{"code": "x"}]}}
        after, changes = mig.migrate_resource_json(rtype, before)
        assert changes == []
        assert after is before

    @pytest.mark.parametrize("bad", [None, "", [], 0, "a string"])
    def test_odd_input_does_not_raise(self, bad):
        """A migration that throws halfway through a table is worse than one
        that skips a row it does not understand."""
        after, changes = mig.migrate_resource_json("Device", bad)
        assert changes == []
        assert after is bad


class TestTheEndToEndPropertyThatMatters:
    def test_a_migrated_absent_device_is_STILL_explicitly_absent(self):
        """The whole reason `code` is renamed rather than dropped.

        Both field names are in `_CODE_BEARING_FIELDS`, so the section
        matcher recognises the row before AND after. This asserts the
        after, because a migration that silently downgraded a REQUIRED-ish
        section's EXPLICITLY_ABSENT to MISSING would be invisible.
        """
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j

        old = {"resourceType": "Device", "status": "unknown",
               "patient": {"reference": PATIENT_REF},
               "code": euips.absent_coding("devices")}
        assert euips.status_for_resources([Row("Device", old)])["devices"] \
            == euips.EXPLICITLY_ABSENT, "precondition"

        new, changes = mig.migrate_resource_json("Device", old)
        assert changes
        assert euips.status_for_resources([Row("Device", new)])["devices"] \
            == euips.EXPLICITLY_ABSENT, \
            "the rename must not downgrade the section"

    def test_a_migrated_device_carries_no_undefined_R5_element(self):
        """Closes the loop with #907's element lists."""
        from tests.test_r5_device_elements_907 import R5_DEVICE_ELEMENTS
        old = {"resourceType": "Device", "status": "active",
               "patient": {"reference": PATIENT_REF},
               "code": {"coding": [{"code": "x"}]}}
        new, _ = mig.migrate_resource_json("Device", old)
        assert not (set(new) - R5_DEVICE_ELEMENTS)


class TestPlan:
    class _R:
        def __init__(s, t, j):
            s.resource_type, s.resource_json = t, j

    def test_it_counts_per_change_and_per_row(self):
        rows = [
            self._R("Device", {"resourceType": "Device",
                               "patient": {"reference": PATIENT_REF}}),
            self._R("Device", {"resourceType": "Device",
                               "code": {"coding": []}}),
            self._R("DeviceUsage", {"resourceType": "DeviceUsage",
                                    "subject": {"reference": PATIENT_REF}}),
            self._R("Device", {"resourceType": "Device", "status": "active"}),
        ]
        p = mig.plan(rows)
        assert p["examined"] == 4
        assert p["affected"] == 3
        assert p["changes"] == {"drop:patient": 1,
                                "rename:code->type": 1,
                                "rename:subject->patient": 1}

    def test_a_row_with_two_changes_counts_once_as_affected(self):
        rows = [self._R("Device", {"resourceType": "Device",
                                   "patient": {"reference": PATIENT_REF},
                                   "code": {"coding": []}})]
        p = mig.plan(rows)
        assert p["affected"] == 1
        assert sum(p["changes"].values()) == 2


class TestTheCli:
    @pytest.fixture
    def seeded(self, client, db):
        fhir = FhirResource(resource_type="Patient",
                            resource_id=str(uuid.uuid4()),
                            resource_json={"resourceType": "Patient"})
        db.session.add(fhir)
        db.session.flush()
        p = PatientIndex(fhir_resource_guid=fhir.guid,
                         resource_id=str(uuid.uuid4()),
                         family_name="Migreringsson", given_name="Test")
        db.session.add(p)
        db.session.flush()
        rows = [
            FhirResource(resource_type="Device",
                         resource_id=str(uuid.uuid4()), version_id=1,
                         patient_guid=p.guid, status="active",
                         resource_json={"resourceType": "Device",
                                        "patient": {"reference": PATIENT_REF},
                                        "type": {"coding": []}}),
            FhirResource(resource_type="DeviceUsage",
                         resource_id=str(uuid.uuid4()), version_id=1,
                         patient_guid=p.guid, status="active",
                         resource_json={"resourceType": "DeviceUsage",
                                        "subject": {"reference": PATIENT_REF}}),
        ]
        db.session.add_all(rows)
        db.session.commit()
        return {"patient": p, "rows": rows}

    def _run(self, client, *args):
        return client.application.test_cli_runner().invoke(
            args=["migrate-r5-device-elements", *args])

    def test_the_default_is_a_DRY_RUN_that_writes_nothing(
            self, client, db, seeded):
        res = self._run(client)
        assert res.exit_code == 0, res.output
        assert "2 would change" in res.output
        assert "dry run" in res.output
        db.session.expire_all()
        dev = db.session.query(FhirResource).filter_by(
            resource_type="Device").first()
        assert "patient" in dev.resource_json, "a dry run must not write"

    def test_apply_writes_and_reports_the_count(self, client, db, seeded):
        res = self._run(client, "--apply")
        assert res.exit_code == 0, res.output
        assert "wrote 2 row(s)" in res.output
        db.session.expire_all()
        dev = db.session.query(FhirResource).filter_by(
            resource_type="Device").first()
        use = db.session.query(FhirResource).filter_by(
            resource_type="DeviceUsage").first()
        assert "patient" not in dev.resource_json
        assert use.resource_json["patient"] == {"reference": PATIENT_REF}

    def test_the_row_patient_guid_is_NEVER_touched(self, client, db, seeded):
        """The linkage. A migration that orphaned rows while tidying their
        JSON would be the worst outcome available here."""
        before = {str(r.resource_id): r.patient_guid for r in seeded["rows"]}
        self._run(client, "--apply")
        db.session.expire_all()
        for rid, guid in before.items():
            row = db.session.query(FhirResource).filter_by(
                resource_id=rid).first()
            assert row.patient_guid == guid

    def test_expect_mismatch_ABORTS_and_writes_nothing(
            self, client, db, seeded):
        res = self._run(client, "--apply", "--expect", "99")
        assert res.exit_code != 0
        assert "ABORT" in str(res.output) + str(res.exception)
        db.session.expire_all()
        dev = db.session.query(FhirResource).filter_by(
            resource_type="Device").first()
        assert "patient" in dev.resource_json, "nothing may be written"

    def test_expect_matching_proceeds(self, client, db, seeded):
        res = self._run(client, "--apply", "--expect", "2")
        assert res.exit_code == 0, res.output
        assert "wrote 2" in res.output

    def test_a_second_apply_is_a_no_op(self, client, db, seeded):
        self._run(client, "--apply")
        res = self._run(client, "--apply")
        assert res.exit_code == 0, res.output
        assert "0 would change" in res.output
