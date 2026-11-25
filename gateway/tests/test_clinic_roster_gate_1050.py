"""#1050: GET /api/v1/clinics/<guid>/patients — the roster a care professional
reads from dashboard's patient picker with their OWN SSO bearer.

Rules under test:
  * a professional bearer needs NO local eps `users` row (require_auth answered
    401 "User not found in local system" for every professional without one);
  * on the BEARER path: SU, or a professional affiliated to the clinic's care
    unit (affiliations[].care_unit_guid; organization_ids is not read) — else
    403 `not_affiliated`; a clinic with no care unit is SU-only;
  * `<guid>` may be the eps Clinic.guid or the sso care-unit guid;
  * the ApiKey path (sim.pdhc, request.pdhc, icd11.pdhc) is UNCHANGED: any
    clinic, no audit row added;
  * a bearer read writes one `clinic_roster_read` audit row with a count and
    never a name or personnummer.

AUTH ON throughout. The only thing patched is the outbound call to sso
(`httpx.get` in auth_service). Personnummer are SYNTHETIC (build_synthetic)
and are never printed.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.user import User
from app.services import personnummer as pnr
from app.services.auth_service import hash_api_key

SSO = "https://sso.test"
UNIT_A = "aaaa1050-0000-4000-8000-0000000000a1"
UNIT_B = "aaaa1050-0000-4000-8000-0000000000b1"


def _blob(kind):
    b = {"user_guid": str(uuid.uuid4()), "email": f"{kind}@example.test",
         "user_type": "professional", "is_su_admin": False,
         "session_phases": [], "affiliations": []}
    if kind in ("pro_a", "pro_a_row", "pro_a_inactive"):
        b["affiliations"] = [{"care_unit_guid": UNIT_A.upper(), "role": "nurse"}]
    elif kind == "su":
        b["is_su_admin"] = True
    elif kind == "patient":
        b["user_type"] = "patient"
        b["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"}]
    elif kind == "legacy_member":
        b["organization_ids"] = [UNIT_A, UNIT_B]
    elif kind == "must_change":
        b["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"}]
        b["must_change_password"] = True
    return b


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeSso:
    def __init__(self):
        self.blobs = {k: _blob(k) for k in ("pro_a", "pro_a_row", "pro_a_inactive", "su",
                                             "patient", "legacy_member", "must_change")}

    def __call__(self, url, headers=None, timeout=None, **kw):
        assert url.startswith(SSO + "/api/auth/me"), url
        tok = (headers or {}).get("Authorization", "")[len("Bearer tok-"):]
        if tok in self.blobs:
            return _Resp(200, self.blobs[tok])
        return _Resp(401, {"error": "invalid"})


def H(kind):
    return {"Authorization": f"Bearer tok-{kind}"}


@pytest.fixture
def api(client):
    cfg = {"AUTH_DISABLED": False, "OAUTH_BASE_URL": SSO,
           "SSO_CLIENT_ID": "eps-test", "SSO_CLIENT_SECRET": "eps-test-secret"}
    with patch.dict(client.application.config, cfg), \
            patch("app.services.auth_service.httpx.get", FakeSso()):
        yield client


def _patient(db, given, family, serial):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     identifier_system=pnr.PERSONNUMMER_SYSTEM,
                     identifier_value=pnr.build_synthetic(date(1971, 3, 4), serial),
                     given_name=given, family_name=family)
    db.session.add(p)
    db.session.flush()
    return p


@pytest.fixture
def world(db):
    a = Clinic(name="Enhet A", organisation_guid=UNIT_A, is_active=True)
    b = Clinic(name="Enhet B", organisation_guid=UNIT_B, is_active=True)
    bare = Clinic(name="Utan enhet", organisation_guid=None, is_active=True)
    db.session.add_all([a, b, bare])
    db.session.flush()
    pa = _patient(db, "Synt", "Alfasson", 11)
    pb = _patient(db, "Synt", "Betasson", 22)
    db.session.add_all([PatientClinicAssignment(patient_guid=pa.guid, clinic_guid=a.guid),
                        PatientClinicAssignment(patient_guid=pb.guid, clinic_guid=b.guid),
                        PatientClinicAssignment(patient_guid=pb.guid, clinic_guid=bare.guid)])
    db.session.add(User(username="pro_a_row@example.test", is_active=True))
    db.session.add(User(username="pro_a_inactive@example.test", is_active=False))
    db.session.commit()
    return {"a": a, "b": b, "bare": bare, "pa": pa, "pb": pb}


def _url(clinic_or_unit):
    g = clinic_or_unit if isinstance(clinic_or_unit, str) else str(clinic_or_unit.guid)
    return f"/api/v1/clinics/{g}/patients"


def _key(db):
    raw = "rosterkey-" + uuid.uuid4().hex
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="svc", prefix=raw[:8],
                          scopes=[], is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


# --------------------------------------------------------------------------

def test_affiliated_professional_without_eps_user_row_reads_own_unit(api, db, world):
    r = api.get(_url(world["a"]), headers=H("pro_a"))
    assert r.status_code == 200, r.get_data(as_text=True)
    rows = r.get_json()
    assert [p["family_name"] for p in rows] == ["Alfasson"]
    assert rows[0]["identifier_value"] == world["pa"].identifier_value
    assert rows[0]["identifier_system"] == pnr.PERSONNUMMER_SYSTEM


def test_care_unit_guid_addresses_the_clinic_too(api, db, world):
    for g in (UNIT_A, UNIT_A.upper()):
        r = api.get(_url(g), headers=H("pro_a"))
        assert r.status_code == 200
        assert [p["family_name"] for p in r.get_json()] == ["Alfasson"]


def test_other_unit_is_403_by_clinic_guid_and_by_unit_guid(api, db, world):
    for target in (world["b"], UNIT_B):
        r = api.get(_url(target), headers=H("pro_a"))
        assert r.status_code == 403
        assert r.get_json()["error"] == "not_affiliated"
        assert "Betasson" not in r.get_data(as_text=True)


def test_an_eps_user_row_does_not_bypass_the_unit_gate(api, db, world):
    assert api.get(_url(world["a"]), headers=H("pro_a_row")).status_code == 200
    assert api.get(_url(world["b"]), headers=H("pro_a_row")).status_code == 403


def test_an_inactive_eps_user_row_is_still_refused(api, db, world):
    assert api.get(_url(world["a"]), headers=H("pro_a_inactive")).status_code == 401


def test_su_reads_any_unit_including_one_without_a_care_unit(api, db, world):
    for target in (world["a"], world["b"], world["bare"]):
        assert api.get(_url(target), headers=H("su")).status_code == 200


def test_a_clinic_without_a_care_unit_is_su_only(api, db, world):
    assert api.get(_url(world["bare"]), headers=H("pro_a")).status_code == 403


def test_memberships_alone_are_not_an_affiliation(api, db, world):
    assert api.get(_url(world["a"]), headers=H("legacy_member")).status_code == 403


def test_a_patient_bearer_is_refused(api, db, world):
    assert api.get(_url(world["a"]), headers=H("patient")).status_code == 401


def test_unknown_bearer_and_must_change_password_are_refused(api, db, world):
    assert api.get(_url(world["a"]), headers=H("nobody")).status_code == 401
    assert api.get(_url(world["a"]), headers=H("must_change")).status_code in (401, 403)


def test_apikey_path_is_unchanged_any_clinic_and_no_roster_audit(api, db, world):
    h = _key(db)
    for target, fam in ((world["a"], "Alfasson"), (world["b"], "Betasson"),
                        (world["bare"], "Betasson")):
        r = api.get(_url(target), headers=h)
        assert r.status_code == 200
        assert [p["family_name"] for p in r.get_json()] == [fam]
    assert db.session.query(AuditLog).filter_by(event_type="clinic_roster_read").count() == 0


def test_unknown_clinic_is_404_and_malformed_is_400(api, db, world):
    assert api.get(_url(str(uuid.uuid4())), headers=H("su")).status_code == 404
    assert api.get(_url("not-a-uuid"), headers=H("su")).status_code == 400


def test_bearer_read_is_audited_without_names_or_personnummer(api, db, world):
    assert api.get(_url(world["a"]), headers=H("pro_a")).status_code == 200
    rows = db.session.query(AuditLog).filter_by(event_type="clinic_roster_read").all()
    assert len(rows) == 1
    assert rows[0].detail == {"patients": 1}
    assert str(rows[0].resource_guid) == str(world["a"].guid)
    dumped = json.dumps([{c.name: str(getattr(r, c.name)) for c in r.__table__.columns}
                         for r in db.session.query(AuditLog).all()])
    assert world["pa"].identifier_value not in dumped
    assert world["pa"].identifier_value.replace("-", "") not in dumped
    assert "Alfasson" not in dumped


# --- GET /api/v1/clinics with a person's bearer (record.pdhc picker) -------

def test_clinic_list_su_bearer_without_eps_row_sees_every_active_clinic(api, db, world):
    r = api.get("/api/v1/clinics", headers=H("su"))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert {c["name"] for c in r.get_json()} == {"Enhet A", "Enhet B", "Utan enhet"}


def test_clinic_list_professional_bearer_sees_only_own_units(api, db, world):
    r = api.get("/api/v1/clinics", headers=H("pro_a"))
    assert r.status_code == 200
    assert [c["name"] for c in r.get_json()] == ["Enhet A"]


def test_clinic_list_professional_without_affiliation_sees_none(api, db, world):
    r = api.get("/api/v1/clinics", headers=H("legacy_member"))
    assert r.status_code == 200 and r.get_json() == []


def test_clinic_list_patient_bearer_refused_and_key_unchanged(api, db, world):
    assert api.get("/api/v1/clinics", headers=H("patient")).status_code == 401
    r = api.get("/api/v1/clinics", headers=_key(db))
    assert r.status_code == 200 and len(r.get_json()) == 3
