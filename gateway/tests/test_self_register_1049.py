"""#1049 (contract s7.2): POST /api/v1/patients/self-register.

sso's registration creates the eps patient. AUTH ON, real ApiKeys, the real
route: under AUTH_DISABLED neither gate runs. Personnummer are SYNTHETIC
(build_synthetic: wrong check digit) and are never printed.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.models.user import User
from app.services import personnummer as pnr
from app.services.auth_service import hash_api_key

SCOPE = "patients:self-register"   # literal: the control must fail on the assertion
URL = "/api/v1/patients/self-register"


def _key(db, scopes):
    raw = f"kreg-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="sso registration",
                          prefix=raw[:8], scopes=scopes, is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


@pytest.fixture
def auth_on(client):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
        yield client


@pytest.fixture
def unit(db):
    u = str(uuid.uuid4())
    c = Clinic(name=f"reg unit {uuid.uuid4().hex[:6]}", organisation_guid=u,
               is_active=True)
    db.session.add(c); db.session.commit()
    return u, c


def _pnr(serial=123):
    return pnr.build_synthetic(date(1984, 3, 7), serial)


def _body(unit_guid, **over):
    b = {"personnummer": _pnr(), "given_name": "Synt", "family_name": "Testsson",
         "care_unit_guid": unit_guid, "email": "synt@example.test",
         "mobile": "+46700000000"}
    b.update(over)
    return b


def test_creates_patient_and_self_registered_active_assignment(auth_on, db, unit):
    u, clinic = unit
    r = auth_on.post(URL, json=_body(u), headers=_key(db, [SCOPE]))
    assert r.status_code == 201, r.get_data(as_text=True)
    guid = r.get_json()["patient_guid"]
    assert r.headers["X-PDHC-Patient-Guid"] == guid
    assert set(r.get_json()) == {"patient_guid"}
    p = db.session.get(PatientIndex, uuid.UUID(guid))
    # one guid (2026-10-08 principle): the FHIR id IS the platform guid
    assert p.resource_id == guid
    assert p.identifier_system == pnr.PERSONNUMMER_SYSTEM
    assert p.identifier_value == pnr.normalise(_pnr())
    assert (p.given_name, p.family_name) == ("Synt", "Testsson")
    assert p.birth_date == date(1984, 3, 7)
    fhir = db.session.query(FhirResource).filter_by(
        resource_type="Patient", resource_id=guid, status="active").one()
    assert fhir.patient_guid == p.guid
    assert {(t["system"], t["value"]) for t in fhir.resource_json.get("telecom", [])} == {
        ("email", "synt@example.test"), ("phone", "+46700000000")}
    a = db.session.query(PatientClinicAssignment).filter_by(patient_guid=p.guid).one()
    assert a.clinic_guid == clinic.guid and a.ended_at is None
    assert a.origin == "self-registered"


def test_every_reader_finds_the_patient(auth_on, db, unit):
    u, clinic = unit
    h = _key(db, [SCOPE])
    guid = auth_on.post(URL, json=_body(u), headers=h).get_json()["patient_guid"]
    # sso's verify_patient reads this route, and matches on care_unit_guid
    with patch.dict(auth_on.application.config, {"AUTH_DISABLED": True}):
        r = auth_on.get(f"/api/v1/patients/{guid}/clinics")
        assert r.status_code == 200
        assert [c["care_unit_guid"] for c in r.get_json()] == [u]
        roster = auth_on.get(f"/api/v1/clinics/{clinic.guid}/patients").get_json()
        assert guid in str(roster)
        assert auth_on.get(f"/fhir/Patient/{guid}").status_code == 200


def test_audited_without_the_personnummer(auth_on, db, unit):
    u, _ = unit
    guid = auth_on.post(URL, json=_body(u), headers=_key(db, [SCOPE])).get_json()["patient_guid"]
    rows = db.session.query(AuditLog).filter_by(event_type="patient_self_registered").all()
    assert len(rows) == 1 and str(rows[0].patient_guid) == guid
    assert rows[0].actor_type == "service"
    digits = pnr.normalise(_pnr()).replace("-", "")
    assert digits not in str(rows[0].detail).replace("-", "")


def test_existing_identifier_is_409_exists_with_nothing_else(auth_on, db, unit):
    u, _ = unit
    h = _key(db, [SCOPE])
    assert auth_on.post(URL, json=_body(u), headers=h).status_code == 201
    # the 12-digit spelling of the same number is the same person
    r = auth_on.post(URL, json=_body(u, personnummer=_pnr().replace("-", ""),
                                     given_name="Other"), headers=h)
    assert r.status_code == 409
    assert r.get_json() == {"error": "exists"}
    assert "X-PDHC-Patient-Guid" not in r.headers
    assert db.session.query(PatientIndex).count() == 1


def test_a_patient_stored_with_the_12_digit_spelling_is_the_same_person(auth_on, db, unit):
    """A FHIR client may have stored the number without the dash."""
    u, _ = unit
    rid = str(uuid.uuid4())
    fhir = FhirResource(resource_type="Patient", resource_id=rid,
                        resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(fhir); db.session.flush()
    db.session.add(PatientIndex(fhir_resource_guid=fhir.guid, resource_id=rid,
                                identifier_value=_pnr().replace("-", ""),
                                family_name="Earlier", given_name="Stored"))
    db.session.commit()
    r = auth_on.post(URL, json=_body(u), headers=_key(db, [SCOPE]))
    assert r.status_code == 409 and r.get_json() == {"error": "exists"}


def test_unknown_or_inactive_unit_is_422_unknown_unit(auth_on, db, unit):
    u, clinic = unit
    h = _key(db, [SCOPE])
    r = auth_on.post(URL, json=_body(str(uuid.uuid4())), headers=h)
    assert r.status_code == 422 and r.get_json() == {"error": "unknown_unit"}
    # an eps clinic guid is not a care unit guid
    r = auth_on.post(URL, json=_body(str(clinic.guid)), headers=h)
    assert r.status_code == 422 and r.get_json() == {"error": "unknown_unit"}
    clinic.is_active = False; db.session.commit()
    r = auth_on.post(URL, json=_body(u), headers=h)
    assert r.status_code == 422 and r.get_json() == {"error": "unknown_unit"}
    assert db.session.query(PatientIndex).count() == 0


def test_unit_matched_case_insensitively_as_sso_does(auth_on, db, unit):
    u, _ = unit
    r = auth_on.post(URL, json=_body(u.upper()), headers=_key(db, [SCOPE]))
    assert r.status_code == 201


def test_real_format_personnummer_is_refused(auth_on, db, unit):
    u, _ = unit
    real_shape = pnr.build(date(1984, 3, 7), 123)     # VALID check digit
    r = auth_on.post(URL, json=_body(u, personnummer=real_shape), headers=_key(db, [SCOPE]))
    assert r.status_code == 422 and r.get_json() == {"error": "real_personnummer"}
    assert db.session.query(PatientIndex).count() == 0


@pytest.mark.parametrize("over,code", [
    ({"personnummer": "19840231-1234"}, "invalid_personnummer"),
    ({"personnummer": "abc"}, "invalid_personnummer"),
])
def test_malformed_personnummer(auth_on, db, unit, over, code):
    u, _ = unit
    # a crash must come back as a 500 the assertion sees, not escape the test
    with patch.dict(auth_on.application.config, {"PROPAGATE_EXCEPTIONS": False}):
        r = auth_on.post(URL, json=_body(u, **over), headers=_key(db, [SCOPE]))
    assert r.status_code == 422 and r.get_json() == {"error": code}


def test_missing_fields_are_named(auth_on, db, unit):
    u, _ = unit
    r = auth_on.post(URL, json={"care_unit_guid": u, "personnummer": _pnr()},
                     headers=_key(db, [SCOPE]))
    assert r.status_code == 422
    assert r.get_json() == {"error": "validation", "fields": ["family_name", "given_name"]}


def test_email_and_mobile_are_optional(auth_on, db, unit):
    u, _ = unit
    b = _body(u); del b["email"]; del b["mobile"]
    r = auth_on.post(URL, json=b, headers=_key(db, [SCOPE]))
    assert r.status_code == 201
    fhir = db.session.query(FhirResource).filter_by(resource_type="Patient").one()
    assert "telecom" not in fhir.resource_json


def test_unscoped_and_other_scoped_keys_are_refused(auth_on, db, unit):
    u, _ = unit
    for scopes in ([], ["blocks:read"], "patients:self-register"):
        r = auth_on.post(URL, json=_body(u), headers=_key(db, scopes))
        assert r.status_code == 403, scopes
    assert db.session.query(PatientIndex).count() == 0


def test_an_sso_human_is_refused_even_an_su(auth_on, db, unit):
    u, _ = unit
    su = User(username="su1049@example.test", email="su1049@example.test",
              display_name="SU", is_active=True, is_superuser=True)
    db.session.add(su); db.session.commit()
    blob = {"email": su.email, "user_type": "professional", "is_su_admin": True}
    with patch("app.services.auth_service.resolve_sso_user", return_value=blob):
        r = auth_on.post(URL, json=_body(u), headers={"Authorization": "Bearer t"})
        assert r.status_code == 403
        # the bearer itself works: an unscoped route admits the same caller
        assert auth_on.get("/api/v1/clinics", headers={"Authorization": "Bearer t"}).status_code == 200
    assert db.session.query(PatientIndex).count() == 0


def test_no_credential_is_401(auth_on, db, unit):
    u, _ = unit
    assert auth_on.post(URL, json=_body(u)).status_code == 401
