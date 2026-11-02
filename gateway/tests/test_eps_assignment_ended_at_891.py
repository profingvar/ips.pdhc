"""#891 (EPS C4) — an assignment could begin but never end.

`patient_clinic_assignments` had `assigned_at` and no end, so a patient who
moved clinic was either still assigned to the old one or had no record of ever
having been. There was no third thing the schema could say, and
`GET /api/v1/clinics/<guid>/patients` — the roster sim.pdhc builds cohorts
from — reads exactly this table.

**Two things had to change, not one.** The column alone would have made "ended"
a TERMINAL state per pair, because `UniqueConstraint(patient_guid,
clinic_guid)` meant a closed row still occupied the pair and a patient
returning to a clinic they had left could not be re-assigned. It is now a
partial unique index over OPEN assignments, so the history is expressible.

**Ten sites join this table and three are authorisation.** Flipping those from
"has an assignment" to "has an ACTIVE assignment" is a tightening — staff at a
clinic the patient has left would lose access — which is probably right and is
still a security change that needs its own verification. So #891 adds the rule
and one canonical way to apply it, flips only the unambiguous consumer, and
records the rest in `CONSUMERS_OF_ASSIGNMENT`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import (
    CONSUMERS_OF_ASSIGNMENT,
    PatientClinicAssignment,
    PatientIndex,
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _seed_patient(db, family="Slutsson"):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid,
                                      "name": [{"family": family}]})
    db.session.add(res)
    db.session.flush()
    pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                      family_name=family, given_name="Test")
    db.session.add(pi)
    db.session.flush()
    return pi


def _clinic(db, name="C4 Clinic"):
    c = Clinic(name=name, organisation_guid=str(uuid.uuid4()))
    db.session.add(c)
    db.session.flush()
    return c


class TestTheColumn:
    def test_a_new_assignment_has_no_end(self, client, db):
        p, c = _seed_patient(db), _clinic(db)
        a = PatientClinicAssignment(patient_guid=p.guid, clinic_guid=c.guid)
        db.session.add(a)
        db.session.commit()
        assert a.ended_at is None, "a fresh assignment must read as open"

    def test_it_is_NOT_a_reuse_of_expires_at(self, db):
        """`expires_at` exists on four other models and means a PLANNED future
        end. This is an end that happened. Reusing the name would make an
        expiry in the future — which means 'still valid' — read as 'over'."""
        cols = {c.name for c in PatientClinicAssignment.__table__.columns}
        assert "ended_at" in cols
        assert "expires_at" not in cols


class TestTheHistoryIsExpressible:
    def test_a_closed_assignment_and_a_NEW_one_can_coexist(self, client, db):
        """What the old unique constraint forbade. A patient who leaves and
        returns is an ordinary event, and before this it could not be
        recorded: closing the row left the pair occupied."""
        p, c = _seed_patient(db), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid, ended_at=NOW))
        db.session.commit()
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid))
        db.session.commit()
        assert (db.session.query(PatientClinicAssignment)
                .filter_by(patient_guid=p.guid, clinic_guid=c.guid)
                .count() == 2)

    def test_TWO_OPEN_assignments_to_the_same_clinic_are_still_refused(self, client, db):
        """The control. Without it the test above would also pass for a change
        that simply dropped uniqueness, which would let the roster return the
        same patient twice."""
        p, c = _seed_patient(db), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid))
        db.session.commit()
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestTheCanonicalRule:
    def test_active_only_excludes_an_ended_assignment(self, client, db):
        p, c = _seed_patient(db), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid, ended_at=NOW))
        db.session.commit()
        q = db.session.query(PatientClinicAssignment).filter_by(
            patient_guid=p.guid)
        assert q.count() == 1
        assert PatientClinicAssignment.active_only(q).count() == 0

    def test_active_only_keeps_an_open_one(self, client, db):
        p, c = _seed_patient(db), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid))
        db.session.commit()
        q = db.session.query(PatientClinicAssignment).filter_by(
            patient_guid=p.guid)
        assert PatientClinicAssignment.active_only(q).count() == 1


class TestTheRosterHonoursIt:
    def test_a_patient_whose_assignment_ENDED_is_gone_from_the_roster(self, client, db):
        """The point of the whole ticket: sim.pdhc builds cohorts from this
        endpoint, so a stale assignment puts a patient in a cohort they left."""
        p, c = _seed_patient(db, family="Lämnadsson"), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid, ended_at=NOW))
        db.session.commit()
        names = [r["family_name"] for r in
                 client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()]
        assert "Lämnadsson" not in names, names

    def test_a_patient_with_an_OPEN_assignment_is_still_there(self, client, db):
        """The control. Without it, a roster that returned nothing at all
        would pass the test above."""
        p, c = _seed_patient(db, family="Kvarsson"), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid))
        db.session.commit()
        names = [r["family_name"] for r in
                 client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()]
        assert "Kvarsson" in names, names

    def test_a_patient_who_LEFT_and_RETURNED_appears_exactly_once(self, client, db):
        """Both halves at once: the history is kept and the roster is not
        duplicated by it."""
        p, c = _seed_patient(db, family="Återsson"), _clinic(db)
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid, ended_at=NOW))
        db.session.commit()
        db.session.add(PatientClinicAssignment(
            patient_guid=p.guid, clinic_guid=c.guid))
        db.session.commit()
        names = [r["family_name"] for r in
                 client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()]
        assert names.count("Återsson") == 1, names


class TestTheInventoryRecordsEverySite:
    """These two tests asserted the three AUTHORISATION paths were still HELD,
    which was true for as long as #891 was the latest word. #899(b) flipped
    them — and these tests are what made that flip impossible to do silently,
    which was their purpose. Rewritten rather than deleted: the old assertions
    recorded a real decision, and the new ones record its successor.

    They were red for exactly the duration of that change and no longer.
    """

    def test_every_site_carries_a_decision(self):
        """No site may sit in the inventory undecided. A blank entry is how a
        join slips back to 'any assignment' without anyone choosing it."""
        undecided = [k for k, v in CONSUMERS_OF_ASSIGNMENT.items() if not v.strip()]
        assert undecided == [], undecided
        assert len(CONSUMERS_OF_ASSIGNMENT) == 10, sorted(CONSUMERS_OF_ASSIGNMENT)

    def test_the_three_AUTHORISATION_sites_are_now_active_only(self):
        """Flipped by #899(b) while it was provably a no-op: `ended_at` was
        NULL on all 296 production rows and nothing could set it."""
        for site in ("api/blocks_routes.py staff authorisation",
                     "api/consents_routes.py staff authorisation",
                     "api/care_access_routes.py"):
            assert CONSUMERS_OF_ASSIGNMENT[site].startswith("ACTIVE ONLY"), site
            assert "#899" in CONSUMERS_OF_ASSIGNMENT[site], site

    def test_nothing_is_marked_HELD_any_more(self):
        held = [k for k, v in CONSUMERS_OF_ASSIGNMENT.items()
                if v.startswith("HELD")]
        assert held == [], held

    def test_the_sites_that_are_still_OPEN_QUESTIONS_are_named(self):
        """Two patient_routes reads and ips_generator remain undecided, and
        saying so is the point — an open question recorded is not the same as
        a join nobody looked at."""
        open_q = sorted(k for k, v in CONSUMERS_OF_ASSIGNMENT.items()
                        if v.startswith("OPEN QUESTION"))
        assert len(open_q) == 2, open_q
        assert all("patient_routes" in k for k in open_q), open_q
        assert CONSUMERS_OF_ASSIGNMENT[
            "services/ips_generator.py managing org"].startswith("PROBABLY HISTORICAL")
