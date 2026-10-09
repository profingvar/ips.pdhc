"""#814 — generate a cohort over HTTP, so one operator task is one UI.

The generator had two callers, the SU-SSO admin form and a Flask CLI command,
so a tool outside a browser could not create a cohort. "Pick a clinic, make 10
patients aged 40-75, then generate their data" is one task; splitting it across
two UIs is how the batch GUID gets lost between them.

This opens no new capability — `POST /api/v1/clinics/<guid>/patients` already
lets an API-key holder create patients, and sim's Synthea importer does it in
bulk. These tests pin the refusals, which are the part worth guarding.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment


def _clinic(db, *, org=True, name="Gen Clinic"):
    c = Clinic(name=name,
               organisation_guid=str(uuid.uuid4()) if org else None)
    db.session.add(c)
    db.session.commit()
    return c


def _url(c):
    return f"/api/v1/clinics/{c.guid}/generate-cohort"


def _age(iso, today=None):
    today = today or date.today()
    b = date.fromisoformat(iso)
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def test_it_creates_patients_and_returns_the_BATCH_GUID(client, db):
    """The batch guid is the point: it is what makes the cohort selectable by
    sim and purgeable as a unit."""
    c = _clinic(db)
    r = client.post(_url(c), json={"count": 4, "age_min": 40, "age_max": 75})
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    assert body["created"] == 4
    assert body["batch_guid"]
    assert len(body["patient_guids"]) == 4

    rows = (_db.session.query(PatientIndex)
            .filter(PatientIndex.generation_batch_guid
                    == uuid.UUID(body["batch_guid"])).all())
    assert len(rows) == 4


def test_every_patient_gets_a_CLINIC_ASSIGNMENT(client, db):
    """A patient with no assignment is invisible to every org-scoped reader —
    the data is collected and then cannot be read by whoever collected it."""
    c = _clinic(db)
    r = client.post(_url(c), json={"count": 3})
    guids = [uuid.UUID(g) for g in r.get_json()["patient_guids"]]
    n = (_db.session.query(PatientClinicAssignment)
         .filter(PatientClinicAssignment.patient_guid.in_(guids))
         .filter(PatientClinicAssignment.clinic_guid == c.guid).count())
    assert n == 3


def test_the_age_range_is_honoured(client, db):
    c = _clinic(db)
    r = client.post(_url(c), json={"count": 6, "age_min": 40, "age_max": 45})
    guids = [uuid.UUID(g) for g in r.get_json()["patient_guids"]]
    made = _db.session.query(PatientIndex).filter(
        PatientIndex.guid.in_(guids)).all()
    ages = [_age(p.birth_date.isoformat()) for p in made]
    assert ages and min(ages) >= 40 and max(ages) <= 45, sorted(ages)
    assert r.get_json()["age_min"] == 40
    assert r.get_json()["age_max"] == 45


def test_a_BAD_age_range_is_400_and_creates_NOBODY(client, db):
    """Refused, not clamped. A cohort generated for the wrong ages looks
    exactly like one generated for the right ages."""
    c = _clinic(db)
    before = _db.session.query(PatientIndex).count()
    r = client.post(_url(c), json={"count": 3, "age_min": 75, "age_max": 40})
    assert r.status_code == 400
    assert "age range" in r.get_json()["error"]
    assert _db.session.query(PatientIndex).count() == before


def test_skip_clinical_DEFAULTS_TO_TRUE_here(client, db):
    """Unlike the admin form. A caller reaching this endpoint is a generator
    pipeline, and the next step is normally sim supplying the observations —
    two sources of clinical truth for one patient is what the flag prevents."""
    c = _clinic(db)
    r = client.post(_url(c), json={"count": 2})
    assert r.get_json()["skip_clinical"] is True


def test_skip_clinical_can_be_turned_OFF(client, db):
    c = _clinic(db)
    r = client.post(_url(c), json={"count": 2, "skip_clinical": False})
    assert r.get_json()["skip_clinical"] is False
    assert r.get_json()["resources"] > 0, "no clinical resources were written"


def test_a_clinic_with_NO_ORGANISATION_is_refused(client, db):
    """Its patients could not be org-scoped, so generating them would create
    exactly the invisible-patient problem this refusal exists to prevent."""
    c = _clinic(db, org=False, name="Orphan Clinic")
    before = _db.session.query(PatientIndex).count()
    r = client.post(_url(c), json={"count": 3})
    assert r.status_code == 409
    assert "organisation_guid" in r.get_json()["error"]
    assert _db.session.query(PatientIndex).count() == before


def test_an_unknown_clinic_is_404_and_a_malformed_guid_is_400(client, db):
    assert client.post(f"/api/v1/clinics/{uuid.uuid4()}/generate-cohort",
                       json={"count": 1}).status_code == 404
    assert client.post("/api/v1/clinics/not-a-guid/generate-cohort",
                       json={"count": 1}).status_code == 400


@pytest.mark.parametrize("bad", [0, -1, "many"])
def test_a_bad_count_is_400(client, db, bad):
    c = _clinic(db)
    r = client.post(_url(c), json={"count": bad})
    assert r.status_code == 400


def test_the_generation_is_AUDITED(client, db):
    """Rule 24. Creating patients is the most consequential thing this
    endpoint does."""
    from app.models.audit_log import AuditLog
    c = _clinic(db)
    client.post(_url(c), json={"count": 2})
    _db.session.rollback()          # only a COMMITTED entry survives
    rows = (_db.session.query(AuditLog)
            .filter_by(event_type="patient_cohort_generate").all())
    assert len(rows) == 1
    assert rows[0].detail.get("batch_guid")
    assert rows[0].detail.get("created") == 2
