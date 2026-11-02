"""#899(b) — three authorisation paths granted on ANY assignment, active or not.

`blocks_routes` (spärr), `consents_routes` and `care_access_routes` all answer
"does this staff member have a `PatientClinicAssignment` to this patient?" and
none asked whether it was still active. After #891 gave assignments an end
date, that meant staff at a clinic the patient had LEFT would keep spärr,
consent and care access.

**Why this was done before anything could end an assignment.** Measured
2026-11-02: `ended_at` was NULL on all 296 production rows and no write path
could set it (#899 part a is still open). So narrowing these queries changed no
real answer on the day it shipped — "has an assignment" and "has an ACTIVE
assignment" returned the same set. That makes the tightening reviewable in
isolation. Done after the first assignment ends, the same edit would be a
behaviour change on a security path with real subjects.

The empirical form of that claim: the full suite went from 792 passing to 790
passing plus the two #891 tests that asserted these paths were untouched. No
other test outcome moved.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.base import db as _db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.models.user import User

ENDED = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def seed(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    patient = PatientIndex(fhir_resource_guid=fhir.guid,
                           resource_id=str(uuid.uuid4()),
                           family_name="Uppdragsson", given_name="Test")
    clinic = Clinic(name="899 Clinic", organisation_guid=str(uuid.uuid4()),
                    is_active=True)
    db.session.add_all([patient, clinic])
    db.session.flush()
    staff = User(username="staff899", email="staff899@example.test",
                 display_name="Staff 899", is_active=True, is_superuser=False)
    db.session.add(staff)
    db.session.flush()
    db.session.add(UserClinicAssignment(user_guid=staff.guid,
                                        clinic_guid=clinic.guid))
    assignment = PatientClinicAssignment(patient_guid=patient.guid,
                                         clinic_guid=clinic.guid)
    db.session.add(assignment)
    db.session.commit()
    return {"patient": patient, "clinic": clinic, "staff": staff,
            "assignment": assignment}


@pytest.fixture
def as_user():
    @contextmanager
    def _impersonate(user):
        with patch("app.services.auth_service._synthetic_dev_user",
                   return_value=user):
            yield
    return _impersonate


def _end(db, seed):
    seed["assignment"].ended_at = ENDED
    db.session.commit()


class TestSparr:
    def test_staff_with_an_ACTIVE_assignment_may_act(self, client, db, seed, as_user):
        """The no-op half: nothing changes while the assignment is open."""
        with as_user(seed["staff"]):
            r = client.get(f"/api/v1/patients/{seed['patient'].guid}/blocks")
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_staff_whose_assignment_ENDED_may_not(self, client, db, seed, as_user):
        _end(db, seed)
        with as_user(seed["staff"]):
            r = client.get(f"/api/v1/patients/{seed['patient'].guid}/blocks")
        assert r.status_code == 403, r.get_data(as_text=True)


class TestConsents:
    def test_staff_with_an_ACTIVE_assignment_may_act(self, client, db, seed, as_user):
        with as_user(seed["staff"]):
            r = client.get(f"/api/v1/patients/{seed['patient'].guid}/consents")
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_staff_whose_assignment_ENDED_may_not(self, client, db, seed, as_user):
        _end(db, seed)
        with as_user(seed["staff"]):
            r = client.get(f"/api/v1/patients/{seed['patient'].guid}/consents")
        assert r.status_code == 403, r.get_data(as_text=True)


class TestCareAccess:
    def test_an_ACTIVE_assignment_resolves_the_care_organisation(self, client, db, seed):
        from app.api.care_access_routes import _assigned_clinic
        assert _assigned_clinic(seed["patient"].guid) is not None

    def test_an_ENDED_assignment_resolves_to_None_which_is_a_DENIAL(self, client, db, seed):
        """None is not 'unknown' here — the caller treats it as a denial, the
        same #807-shaped case as a patient with no care relationship at all."""
        from app.api.care_access_routes import _assigned_clinic
        _end(db, seed)
        assert _assigned_clinic(seed["patient"].guid) is None


class TestWhatWasNotTightened:
    def test_an_ADMIN_is_unaffected_by_an_ended_assignment(self, client, db, seed):
        """The control that this is an assignment rule and not a new blanket
        denial. The default test client is the synthetic SU, which short-circuits
        the gate before any assignment is consulted."""
        _end(db, seed)
        r = client.get(f"/api/v1/patients/{seed['patient'].guid}/consents")
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_an_unrelated_clinic_was_already_refused(self, client, db, seed, as_user):
        """Pre-existing behaviour, asserted so the new rule is not credited
        with it: staff at a clinic with NO assignment to this patient were
        always refused, ended or not."""
        other = User(username="other899", email="other899@example.test",
                     display_name="Other 899", is_active=True,
                     is_superuser=False)
        _db.session.add(other)
        _db.session.commit()
        with as_user(other):
            r = client.get(f"/api/v1/patients/{seed['patient'].guid}/consents")
        assert r.status_code == 403
