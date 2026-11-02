"""#900 (EPS C4c) — the write path that can actually END an assignment.

#891 gave `patient_clinic_assignments` an `ended_at` and the partial unique
index that makes history expressible. #899(b) made spärr, consent and care
access honour it. #901 made the state projection follow it. **Nothing could
SET it**, so the whole chain guarded a state that never occurred — a column
nothing populates.

The tests worth reading are the two refusals, because they are where the
distinction #891 drew either holds or quietly collapses:

  - `test_a_FUTURE_ended_at_is_refused` — a planned future end is an EXPIRY,
    and `ended_at` is not `expires_at`: an expiry in the future means "still
    valid" while a non-NULL `ended_at` always means "over".
  - `test_ended_before_assigned_is_refused` — an interval that ends before it
    begins is not a bad date, it is an impossible fact.

And `TestItMakes899Live` is the point of the whole chain: after this, ending an
assignment actually removes access.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db as _db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.patient_state import PatientStateFact
from app.models.user import User
from app.services import patient_assignment as pa


def _patient(db, family="Uppdragsson"):
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
    res.patient_guid = pi.guid
    db.session.commit()
    return pi


def _clinic(db, name):
    c = Clinic(name=name, organisation_guid=str(uuid.uuid4()), is_active=True)
    db.session.add(c)
    db.session.flush()
    db.session.commit()
    return c


def _staff(db, label, clinic):
    u = User(username=label, email=f"{label}@x.test", display_name=label,
             is_active=True, is_superuser=False)
    db.session.add(u)
    db.session.flush()
    db.session.add(UserClinicAssignment(user_guid=u.guid,
                                        clinic_guid=clinic.guid))
    db.session.commit()
    return u


def _admin(db):
    u = User(username=f"adm{uuid.uuid4().hex[:6]}", email="a900@x.test",
             display_name="Admin", is_active=True, is_superuser=True)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def acting(app):
    @contextmanager
    def _acting(user):
        with app.test_request_context("/api/v1/patients/x/assignments",
                                      method="POST"):
            from flask import g as _g
            _g.current_user = user
            yield
    return _acting


class TestAssign:
    def test_an_admin_can_open_an_assignment(self, client, db, acting):
        p, c, a = _patient(db), _clinic(db, "A900"), _admin(db)
        with acting(a):
            row = pa.assign(p.guid, c.guid)
            db.session.commit()
        assert row.ended_at is None
        assert row.assigned_at is not None

    def test_a_SECOND_open_assignment_is_refused_BY_NAME(self, client, db, acting):
        """The partial unique index would refuse this too, but as a 500 with a
        constraint name — which tells a caller nothing about what to do."""
        p, c, a = _patient(db), _clinic(db, "B900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            with pytest.raises(pa.AlreadyAssigned) as e:
                pa.assign(p.guid, c.guid)
        assert "already has an open assignment" in str(e.value)

    def test_RE_assigning_after_an_END_is_allowed(self, client, db, acting):
        """"Left and came back" is the case #891's partial index exists for, so
        `assign` must refuse only an OPEN duplicate, not a closed one."""
        p, c, a = _patient(db), _clinic(db, "C900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            pa.end(p.guid, c.guid)
            db.session.commit()
            pa.assign(p.guid, c.guid)
            db.session.commit()
        rows = (_db.session.query(PatientClinicAssignment)
                .filter_by(patient_guid=p.guid, clinic_guid=c.guid).all())
        assert len(rows) == 2, len(rows)
        assert sum(1 for r in rows if r.ended_at is None) == 1


class TestEnd:
    def test_it_sets_ended_at_rather_than_DELETING(self, client, db, acting):
        """Deleting is what the column exists to replace: it loses that the
        patient was ever there, which is the half of the problem #891 was
        filed for."""
        p, c, a = _patient(db), _clinic(db, "D900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            pa.end(p.guid, c.guid)
            db.session.commit()
        rows = (_db.session.query(PatientClinicAssignment)
                .filter_by(patient_guid=p.guid, clinic_guid=c.guid).all())
        assert len(rows) == 1, "the row was deleted instead of ended"
        assert rows[0].ended_at is not None

    def test_a_BACKDATED_end_is_accepted(self, client, db, acting):
        """Learning of a move after the fact is the ordinary case, not an edge
        one — which is why `ended_at` is a parameter and not `utcnow()`."""
        p, c, a = _patient(db), _clinic(db, "E900"), _admin(db)
        past = datetime.now(timezone.utc) - timedelta(days=10)
        with acting(a):
            pa.assign(p.guid, c.guid,
                      assigned_at=datetime.now(timezone.utc) - timedelta(days=40))
            db.session.commit()
            row = pa.end(p.guid, c.guid, ended_at=past)
            db.session.commit()
        assert row.ended_at.replace(tzinfo=None) == past.replace(tzinfo=None)

    def test_a_FUTURE_ended_at_is_refused(self, client, db, acting):
        """A planned future end is an EXPIRY. #891's model note is explicit
        that `ended_at` is not `expires_at`: an expiry in the future means
        "still valid", a non-NULL `ended_at` always means "over". Accepting a
        future date would make that false for every consumer."""
        p, c, a = _patient(db), _clinic(db, "F900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            with pytest.raises(pa.ImpossibleInterval) as e:
                pa.end(p.guid, c.guid,
                       ended_at=datetime.now(timezone.utc) + timedelta(days=5))
        assert "expiry" in str(e.value)

    def test_ended_before_assigned_is_refused(self, client, db, acting):
        """Not a bad date — an impossible fact."""
        p, c, a = _patient(db), _clinic(db, "G900"), _admin(db)
        now = datetime.now(timezone.utc)
        with acting(a):
            pa.assign(p.guid, c.guid, assigned_at=now - timedelta(days=2))
            db.session.commit()
            with pytest.raises(pa.ImpossibleInterval) as e:
                pa.end(p.guid, c.guid, ended_at=now - timedelta(days=10))
        assert "cannot end before it begins" in str(e.value)

    def test_ending_a_non_existent_assignment_is_refused(self, client, db, acting):
        p, c, a = _patient(db), _clinic(db, "H900"), _admin(db)
        with acting(a), pytest.raises(pa.NotAssigned):
            pa.end(p.guid, c.guid)


class TestWhoMayChangeIt:
    def test_staff_at_THAT_clinic_may(self, client, db, acting):
        p, c = _patient(db), _clinic(db, "I900")
        s = _staff(db, "s900a", c)
        with acting(s):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            pa.end(p.guid, c.guid)
            db.session.commit()
        assert _db.session.query(PatientClinicAssignment).filter_by(
            patient_guid=p.guid).one().ended_at is not None

    def test_staff_at_ANOTHER_clinic_may_NOT(self, client, db, acting):
        """Deliberately narrower than "may see the patient": ending an
        assignment removes access for everyone at that clinic, so being able to
        read a patient is not reason enough to detach them from a clinic you
        have nothing to do with."""
        p, here, there = _patient(db), _clinic(db, "J900"), _clinic(db, "K900")
        s = _staff(db, "s900b", here)
        a = _admin(db)
        with acting(a):
            pa.assign(p.guid, there.guid)
            db.session.commit()
        with acting(s), pytest.raises(pa.NotPermitted):
            pa.end(p.guid, there.guid)


class TestItMakes899Live:
    def test_ending_an_assignment_REMOVES_consent_access(self, client, db, acting):
        """The point of the whole chain. #899(b) narrowed three authorisation
        paths to ACTIVE assignments while nothing could end one; this is the
        first time that narrowing has an effect."""
        from app.api.consents_routes import _can_act_on_patient
        p, c = _patient(db), _clinic(db, "L900")
        s = _staff(db, "s900c", c)
        a = _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
        with acting(s):
            assert _can_act_on_patient(p.guid) is True
        with acting(s):
            pa.end(p.guid, c.guid)
            db.session.commit()
        with acting(s):
            assert _can_act_on_patient(p.guid) is False, \
                "#899b's narrowing had no effect"

    def test_ending_removes_the_patient_from_the_roster(self, client, db, acting):
        p, c, a = _patient(db), _clinic(db, "M900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
        names = [r["family_name"] for r in
                 client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()]
        assert "Uppdragsson" in names
        with acting(a):
            pa.end(p.guid, c.guid)
            db.session.commit()
        names = [r["family_name"] for r in
                 client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()]
        assert "Uppdragsson" not in names

    def test_the_state_projection_follows(self, client, db, acting):
        """#901's trigger: the assignment fact's validity closes."""
        p, c, a = _patient(db), _clinic(db, "N900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
        f = (_db.session.query(PatientStateFact)
             .filter_by(patient_guid=p.guid, fact_type="clinic_assignment")
             .one())
        assert f.valid_to is None
        with acting(a):
            pa.end(p.guid, c.guid)
            db.session.commit()
        f = (_db.session.query(PatientStateFact)
             .filter_by(patient_guid=p.guid, fact_type="clinic_assignment")
             .one())
        assert f.valid_to is not None, "the projection did not follow the end"


class TestAudit:
    def test_both_operations_write_a_row_naming_the_clinic(self, client, db, acting):
        p, c, a = _patient(db), _clinic(db, "O900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            pa.end(p.guid, c.guid)
            db.session.commit()
        rows = {r.event_type: r for r in _db.session.query(AuditLog)
                .filter(AuditLog.patient_guid == p.guid).all()}
        assert "patient.assigned" in rows
        assert "patient.assignment_ended" in rows
        assert rows["patient.assigned"].detail["clinic_guid"] == str(c.guid)

    def test_the_END_row_records_the_CONSEQUENCE(self, client, db, acting):
        """Someone reading the log cares that access was removed, not only that
        a timestamp was written."""
        p, c, a = _patient(db), _clinic(db, "P900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid)
            db.session.commit()
            pa.end(p.guid, c.guid)
            db.session.commit()
        row = (_db.session.query(AuditLog)
               .filter(AuditLog.patient_guid == p.guid,
                       AuditLog.event_type == "patient.assignment_ended").one())
        assert "spärr" in row.detail["effect"]
        assert row.detail["backdated"] is False

    def test_a_backdated_end_is_MARKED_as_such(self, client, db, acting):
        p, c, a = _patient(db), _clinic(db, "Q900"), _admin(db)
        with acting(a):
            pa.assign(p.guid, c.guid,
                      assigned_at=datetime.now(timezone.utc) - timedelta(days=9))
            db.session.commit()
            pa.end(p.guid, c.guid,
                   ended_at=datetime.now(timezone.utc) - timedelta(days=3))
            db.session.commit()
        row = (_db.session.query(AuditLog)
               .filter(AuditLog.patient_guid == p.guid,
                       AuditLog.event_type == "patient.assignment_ended").one())
        assert row.detail["backdated"] is True


class TestTheRoutes:
    def test_assign_then_end_over_HTTP(self, client, db):
        p, c = _patient(db), _clinic(db, "R900")
        r = client.post(f"/api/v1/patients/{p.guid}/assignments",
                        json={"clinic_guid": str(c.guid)})
        assert r.status_code == 201, r.get_data(as_text=True)
        r = client.post(
            f"/api/v1/patients/{p.guid}/assignments/{c.guid}/end", json={})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["ended_at"] is not None
        assert "spärr" in r.get_json()["effect"]

    def test_a_duplicate_assign_is_409_with_its_OWN_code(self, client, db):
        """Each refusal gets its own code: "already assigned" and "no open
        assignment" need different actions and a shared code would make them
        indistinguishable in a client log."""
        p, c = _patient(db), _clinic(db, "S900")
        client.post(f"/api/v1/patients/{p.guid}/assignments",
                    json={"clinic_guid": str(c.guid)})
        r = client.post(f"/api/v1/patients/{p.guid}/assignments",
                        json={"clinic_guid": str(c.guid)})
        assert r.status_code == 409
        assert r.get_json()["code"] == "already_assigned"

    def test_ending_what_is_not_open_is_404_not_assigned(self, client, db):
        p, c = _patient(db), _clinic(db, "T900")
        r = client.post(
            f"/api/v1/patients/{p.guid}/assignments/{c.guid}/end", json={})
        assert r.status_code == 404
        assert r.get_json()["code"] == "not_assigned"

    def test_a_future_ended_at_over_HTTP_is_400(self, client, db):
        p, c = _patient(db), _clinic(db, "U900")
        client.post(f"/api/v1/patients/{p.guid}/assignments",
                    json={"clinic_guid": str(c.guid)})
        future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
        r = client.post(f"/api/v1/patients/{p.guid}/assignments/{c.guid}/end",
                        json={"ended_at": future})
        assert r.status_code == 400
        assert r.get_json()["code"] == "impossible_interval"

    def test_a_bad_date_is_400_not_500(self, client, db):
        p, c = _patient(db), _clinic(db, "V900")
        r = client.post(f"/api/v1/patients/{p.guid}/assignments",
                        json={"clinic_guid": str(c.guid),
                              "assigned_at": "last tuesday"})
        assert r.status_code == 400
        assert "assigned_at" in r.get_json()["error"]
