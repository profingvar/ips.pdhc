"""#825 — ips answers "which patients match this predicate", not the CDRs.

analyse.pdhc resolved a cohort by fanning out `GET /api/v1/fhir/Patient`
across the CDRs. No CDR has ever held a Patient resource and nothing on the
platform creates one, so every cohort resolved to the empty set on every
predicate. Measured 2026-10-13: cdr1/cdr2/cdr3 each 0 rows in `patient`, while
cdr2 and cdr3 held 30 patients' worth of observations apiece.

ips owns the registry, so ips answers the question. These tests pin the two
things that make that safe: the answer is GUIDs only, and the age boundary is
right.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment


def _seed(db, *, birth_date, gender):
    """Match the convention the other ips tests use: let guid default, and
    create the FhirResource the index row points at. Passing uuid objects for
    guid columns fails on SQLite with 'type UUID is not supported'."""
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     birth_date=birth_date, gender=gender, is_active=True)
    db.session.add(p)
    db.session.flush()
    return p

URL = "/api/v1/patients/search"


def _years_ago(years, *, plus_days=0):
    t = date.today()
    try:
        d = t.replace(year=t.year - years)
    except ValueError:
        d = t.replace(year=t.year - years, day=28)
    return d + timedelta(days=plus_days)


@pytest.fixture
def people(app):
    """Three patients at known ages, in two organisations."""
    with app.app_context():
        org_a, org_b = str(uuid.uuid4()), str(uuid.uuid4())
        c_a = Clinic(name="A", organisation_guid=org_a)
        c_b = Clinic(name="B", organisation_guid=org_b)
        db.session.add_all([c_a, c_b])
        db.session.flush()

        made = {}
        for label, age, gender, clinic in (("young", 30, "male", c_a),
                                           ("mid", 50, "female", c_a),
                                           ("old", 80, "female", c_b)):
            p = _seed(db, birth_date=_years_ago(age), gender=gender)
            db.session.add(PatientClinicAssignment(
                patient_guid=p.guid, clinic_guid=clinic.guid))
            made[label] = str(p.guid)
        db.session.commit()
        made["org_a"], made["org_b"] = org_a, org_b
        made["clinic_a"] = str(c_a.guid)
    # Return OUTSIDE the app context. Yielding inside it keeps the context
    # pushed across the whole test and the conftest's own app fixture then
    # tears down underneath it, which surfaces as an ExceptionGroup at
    # teardown while the test itself passes.
    return made


def _post(client, body):
    r = client.post(URL, json=body)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()


def test_it_returns_GUIDS_ONLY_never_demographics(client, people):
    """The caller asked who matches, not for their birth dates. Answering with
    demographics hands identifying data to a service designed not to hold it."""
    body = _post(client, {})
    assert set(body) == {"patient_guids", "count"}
    assert all(isinstance(g, str) for g in body["patient_guids"])
    blob = str(body)
    for leak in ("birth_date", "gender", "family_name", "identifier",
                 "personnummer", "given_name"):
        assert leak not in blob, f"{leak} leaked into a search result"


def test_no_predicate_returns_everyone(client, people):
    got = set(_post(client, {})["patient_guids"])
    assert {people["young"], people["mid"], people["old"]} <= got


def test_age_min_and_max_are_INCLUSIVE(client, people):
    """A 50-year-old must match age_min=50 and age_max=50. An off-by-one here
    silently changes who is in a published cohort."""
    assert people["mid"] in _post(client, {"age_min": 50})["patient_guids"]
    assert people["mid"] in _post(client, {"age_max": 50})["patient_guids"]
    assert people["mid"] in _post(
        client, {"age_min": 50, "age_max": 50})["patient_guids"]


def test_the_band_excludes_who_it_should(client, people):
    got = set(_post(client, {"age_min": 40, "age_max": 70})["patient_guids"])
    assert people["mid"] in got
    assert people["young"] not in got
    assert people["old"] not in got


def test_someone_one_day_from_their_birthday_is_still_the_younger_age(client, app):
    """The boundary case the date arithmetic exists for. A patient who turns 40
    tomorrow is 39 today and must NOT match age_min=40."""
    with app.app_context():
        p = _seed(db, birth_date=_years_ago(40, plus_days=1), gender="other")
        db.session.commit()
        guid = str(p.guid)
    assert guid not in _post(client, {"age_min": 40})["patient_guids"]
    assert guid in _post(client, {"age_max": 39})["patient_guids"]


def test_sex_filter_is_case_insensitive(client, people):
    for spelling in ("female", "FEMALE", "Female"):
        got = set(_post(client, {"sex": spelling})["patient_guids"])
        assert people["mid"] in got and people["young"] not in got


def test_organisation_scoping_is_Rule_24(client, people):
    got = set(_post(client, {"organisation_guids": [people["org_a"]]})["patient_guids"])
    assert {people["young"], people["mid"]} <= got
    assert people["old"] not in got


def test_an_EMPTY_organisation_list_matches_NOBODY(client, people):
    """`[]` means "scoped to no organisation", which is not the same as "no
    scoping". Treating it as absent would hand a caller with no organisations
    the whole registry — the Rule 24 failure direction."""
    assert _post(client, {"organisation_guids": []})["patient_guids"] == []


def test_archived_patients_are_excluded_by_default(client, app, people):
    from datetime import datetime, timezone
    with app.app_context():
        p = db.session.query(PatientIndex).filter_by(
            guid=uuid.UUID(people["mid"])).one()
        p.archived_at = datetime.now(timezone.utc)
        db.session.commit()
    assert people["mid"] not in _post(client, {})["patient_guids"]
    assert people["mid"] in _post(client, {"include_archived": True})["patient_guids"]


def test_a_malformed_guid_is_400_not_500(client, people):
    """A non-UUID in an IN clause raises at the driver. A 500 is
    indistinguishable from ips being down, and a caller fail-closes the whole
    cohort and blames the wrong service — the #825/analysis-filter lesson."""
    r = client.post(URL, json={"organisation_guids": ["not-a-uuid"]})
    assert r.status_code == 400
    assert "malformed" in r.get_json()["error"]


def test_a_reversed_age_band_is_refused(client, people):
    r = client.post(URL, json={"age_min": 70, "age_max": 40})
    assert r.status_code == 400


def test_a_non_integer_age_is_refused(client, people):
    r = client.post(URL, json={"age_min": "forty"})
    assert r.status_code == 400
