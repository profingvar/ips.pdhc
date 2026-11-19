"""ips's external read door (2026-11-19): read grant -> patients of the grant's
organisations (exact match on clinic.organisation_guid), filtered by the
grant's own consent purpose."""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.api import external_read_routes as er
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex

ORG_A, ORG_B, ORG_PARENT = (str(uuid.uuid4()) for _ in range(3))
H = {"Authorization": "Bearer rg.11111111-1111-1111-1111-111111111111.s"}
PROJ = str(uuid.uuid4())


def _resp(code, body=None):
    r = MagicMock(status_code=code); r.json.return_value = body or {}
    return r


@pytest.fixture
def sso(client):
    state = {"grant": {"grant_guid": "g1", "partner_guid": "p1", "org_guids": [ORG_A],
                       "cdrs": ["ips"], "purpose_code": "statistics",
                       "research_project_guids": [], "expires_at": "2026-11-21T00:00:00+00:00"},
             "answer": None, "calls": []}

    def post(url, json=None, headers=None, timeout=None):
        state["calls"].append(json)
        return state["answer"] or _resp(200, state["grant"])

    cfg = {"OAUTH_BASE_URL": "http://sso", "SSO_CLIENT_ID": "c", "SSO_CLIENT_SECRET": "s"}
    with patch.dict(client.application.config, cfg), \
            patch.object(er.httpx, "post", side_effect=post):
        yield state


def _clinic(db, org, parent=None):
    c = Clinic(name=f"k-{org[:6]}", organisation_guid=org, care_organisation_guid=parent or org)
    db.session.add(c); db.session.flush()
    return c


def _patient(db, clinic, *, opt_out=False, projects=(), ended=False, active=True):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir); db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     identifier_value="19121212-1212", family_name="Hemligsson", given_name="Greta",
                     birth_date=date(1970, 2, 3), gender="male", is_active=active,
                     ehds_opt_out=opt_out, consented_research_projects=list(projects))
    db.session.add(p); db.session.flush()
    db.session.add(PatientClinicAssignment(
        patient_guid=p.guid, clinic_guid=clinic.guid,
        ended_at=datetime.now(timezone.utc) if ended else None))
    db.session.commit()
    return str(p.guid)


def test_lists_exactly_the_grants_organisation_minus_opt_outs(client, db, sso):
    a, b = _clinic(db, ORG_A, parent=ORG_PARENT), _clinic(db, ORG_B)
    keep = _patient(db, a)
    opted = _patient(db, a, opt_out=True)
    left = _patient(db, a, ended=True)
    gone = _patient(db, a, active=False)
    other = _patient(db, b)
    r = client.get("/external/v1/patients", headers=H)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["patients"] == [keep]
    assert sso["calls"][0]["cdr"] == "ips"
    for x in (opted, left, gone, other):
        assert x not in r.get_json()["patients"]


def test_parent_org_does_not_include_its_units(client, db, sso):
    a = _clinic(db, ORG_A, parent=ORG_PARENT)
    _patient(db, a)
    sso["grant"]["org_guids"] = [ORG_PARENT]
    assert client.get("/external/v1/patients", headers=H).get_json()["patients"] == []


def test_research_purpose_needs_the_patients_consent_to_a_grant_project(client, db, sso):
    a = _clinic(db, ORG_A)
    yes = _patient(db, a, projects=[PROJ])
    no = _patient(db, a)
    sso["grant"].update(purpose_code="research", research_project_guids=[PROJ])
    assert client.get("/external/v1/patients", headers=H).get_json()["patients"] == [yes]
    sso["grant"].update(research_project_guids=[])
    assert client.get("/external/v1/patients", headers=H).get_json()["patients"] == []
    assert no


def test_patient_view_is_de_identified_and_scoped(client, db, sso):
    a, b = _clinic(db, ORG_A), _clinic(db, ORG_B)
    p, q = _patient(db, a), _patient(db, b)
    r = client.get(f"/external/v1/patients/{p}", headers=H)
    assert r.status_code == 200
    body = r.get_json()["patient"]
    assert (body["patient_guid"], body["sex"], body["birth_year"]) == (p, "male", 1970)
    text = r.get_data(as_text=True)
    for leak in ("19121212", "Hemligsson", "Greta", "1970-02-03"):
        assert leak not in text
    assert client.get(f"/external/v1/patients/{q}", headers=H).status_code == 404
    assert client.get("/external/v1/patients/not-a-uuid", headers=H).status_code == 404


def test_refusals(client, db, sso):
    assert client.get("/external/v1/patients").status_code == 401
    sso["answer"] = _resp(403, {"reason": "cdr_not_granted"})
    r = client.get("/external/v1/patients", headers=H)
    assert r.status_code == 403 and r.get_json()["reason"] == "cdr_not_granted"
    sso["answer"] = _resp(500)
    assert client.get("/external/v1/patients", headers=H).status_code == 503
    sso["answer"] = None
    sso["grant"]["purpose_code"] = None
    assert client.get("/external/v1/patients", headers=H).status_code == 403
