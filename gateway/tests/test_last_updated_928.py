"""#928 — `last_updated` now means its name, and a difference means something.

WHAT WAS WRONG. The column carried `default=utcnow` and no `onupdate`, so it
was set on INSERT and never touched again: a CREATION timestamp wearing a
modification timestamp's name. It also carries an index,
`ix_fhir_resources_last_updated`, which invites exactly the "what changed
recently" query it cannot answer — and two live queries take the invitation,
`fhir_service.search_resources` and `admin.patient_detail`, both
`order_by(last_updated.desc())`.

THE PART THE TICKET DID NOT HAVE, measured in production 2026-11-04 across all
4780 rows:

    rows where last_updated != created_at   2355  (49%)
    largest difference                        14 µs
    last_updated EARLIER than created_at    2355
    last_updated LATER                         0

A modification can only ever be LATER. Every difference running the other way
is proof these were two independent `utcnow()` calls in one INSERT, evaluated
in declaration order — `last_updated` was declared first. So half the table
looked modified to anyone reading `last_updated != created_at` as evidence,
which is the kind of reasoning #927's investigation rested on.

AND THE VERSIONING WAS NOT BROKEN, it had simply never run. `update_resource`
is append-only: it INSERTS a new row at `version_id + 1` and marks the old one
`status='superseded'`. Measured the same day: 4780 rows, all `active`, 0
superseded, 0 duplicated `(resource_type, resource_id)` pairs. So
`max(version_id) = 1` everywhere is not a bug in the bump — the path has never
been called.

WHY `version_id` IS NOT BUMPED IN PLACE, which is a correction to this ticket's
suggested fix. The two in-place writers (`app/__init__.py:257`,
`euips_header_backfill.py:178`) assign `resource_json` directly. In this model
v2 means v1 SURVIVES as superseded; a row claiming v2 with no v1 would assert a
history that does not exist, which is worse than the silence it replaced. A
time is a claim this schema can keep, so `onupdate` is the whole signal for
those two.
"""
import time

import pytest

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.services import fhir_service


def _mk(db, rtype="Observation", rid=None, patient=None):
    import uuid
    row = FhirResource(
        resource_type=rtype,
        resource_id=rid or f"probe928-{uuid.uuid4()}",
        resource_json={"resourceType": rtype, "id": rid or "x"},
        patient_guid=patient,
        status="active",
    )
    db.session.add(row)
    db.session.commit()
    return row


class TestOnInsertTheyShareOneClockRead:
    def test_created_at_and_last_updated_are_EQUAL(self, app, db):
        """They were microseconds apart before #928, because `default=utcnow`
        is evaluated once per COLUMN."""
        row = _mk(db)
        assert row.created_at == row.last_updated

    def test_last_updated_is_NEVER_earlier(self, app, db):
        """The production proof, as an invariant. 2355 of 4780 rows had
        `last_updated` earlier than `created_at`, which a modification can
        never be."""
        for _ in range(5):
            row = _mk(db)
            assert row.last_updated >= row.created_at, (
                "last_updated is earlier than created_at — the two clock reads "
                "are back")

    def test_a_DIFFERENCE_now_means_something(self, app, db):
        """The whole point. Before #928 half the table differed and none of it
        was a modification, so the comparison carried no information."""
        row = _mk(db)
        assert row.created_at == row.last_updated, "a fresh row must not differ"
        time.sleep(0.01)
        row.resource_json = {"resourceType": "Observation", "id": "touched"}
        db.session.commit()
        assert row.last_updated > row.created_at, (
            "after a modification the two MUST differ, or the column is still "
            "a creation timestamp")


class TestOnUpdateItMoves:
    def test_an_in_place_resource_json_write_moves_it(self, app, db):
        """This is the write shape of both in-place writers:
        `row.resource_json = body`."""
        row = _mk(db)
        before = row.last_updated
        time.sleep(0.01)
        row.resource_json = {"resourceType": "Observation", "id": "v2ish"}
        db.session.commit()
        assert row.last_updated > before

    def test_created_at_does_NOT_move(self, app, db):
        """Without this, the test above would pass for an `onupdate` applied to
        the wrong column."""
        row = _mk(db)
        was = row.created_at
        time.sleep(0.01)
        row.resource_json = {"resourceType": "Observation", "id": "v2ish"}
        db.session.commit()
        assert row.created_at == was

    def test_it_does_NOT_bump_version_id(self, app, db):
        """Deliberate, and a correction to #928's suggested fix. In this model
        v2 means v1 survives as `status='superseded'`. A row claiming v2 with
        no v1 would assert a history that does not exist."""
        row = _mk(db)
        row.resource_json = {"resourceType": "Observation", "id": "v2ish"}
        db.session.commit()
        assert row.version_id == 1

    def test_CONTROL_a_no_op_commit_does_not_move_it(self, app, db):
        """`onupdate` fires on an UPDATE statement, and SQLAlchemy emits none
        when nothing changed. Without this the tests above would pass for a
        column that moved on every commit, which would be just as uninformative
        as never moving."""
        row = _mk(db)
        was = row.last_updated
        time.sleep(0.01)
        db.session.commit()
        db.session.refresh(row)
        assert row.last_updated == was


class TestTheAppendOnlyModelIsUntouched:
    """CONTROLS. #928 changes a timestamp; it must not change versioning."""

    def test_update_resource_still_creates_a_NEW_row(self, app, db):
        row = _mk(db, rtype="Condition")
        rid = row.resource_id
        new = fhir_service.update_resource(
            "Condition", rid, {"resourceType": "Condition", "id": rid})
        assert new is not None
        assert new.guid != row.guid, "it updated in place"
        assert new.version_id == 2

    def test_and_still_supersedes_the_old_one(self, app, db):
        row = _mk(db, rtype="Condition")
        rid = row.resource_id
        fhir_service.update_resource(
            "Condition", rid, {"resourceType": "Condition", "id": rid})
        db.session.refresh(row)
        assert row.status == "superseded", (
            "v2 means v1 survives as superseded — that is what makes a version "
            "claim honest here")

    def test_the_new_version_gets_its_own_insert_timestamps(self, app, db):
        """A new version is a new row, so its two timestamps share one clock
        read like any other insert."""
        row = _mk(db, rtype="Condition")
        rid = row.resource_id
        new = fhir_service.update_resource(
            "Condition", rid, {"resourceType": "Condition", "id": rid})
        assert new.created_at == new.last_updated


class TestTheIndexsQueryNowAnswers:
    def test_search_resources_returns_MODIFICATION_order(self, app, db):
        """`fhir_service.search_resources` orders by `last_updated.desc()`.
        Before #928 that was creation order wearing another name; a resource
        edited in place stayed where it was created."""
        import uuid
        pg = uuid.uuid4()
        older = _mk(db, rtype="Procedure", patient=pg)
        time.sleep(0.01)
        newer = _mk(db, rtype="Procedure", patient=pg)

        # sanity: creation order puts `newer` first
        got = fhir_service.search_resources("Procedure")
        mine = [r for r in got if r.guid in (older.guid, newer.guid)]
        assert [r.guid for r in mine] == [newer.guid, older.guid]

        time.sleep(0.01)
        older.resource_json = {"resourceType": "Procedure", "id": "touched"}
        db.session.commit()

        got = fhir_service.search_resources("Procedure")
        mine = [r for r in got if r.guid in (older.guid, newer.guid)]
        assert [r.guid for r in mine] == [older.guid, newer.guid], (
            "the edited resource did not move to the front — the ordering is "
            "still creation order")
