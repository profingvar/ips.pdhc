"""#1050: the invite's eps reads with a care professional's OWN SSO bearer.

    GET /api/v1/patients/<guid>/state
    GET /api/v1/patients/<guid>/clinics

Production 2026-11-22: eps `users` holds ONE row, so under `require_auth` both
answered 401 "User not found in local system" to essentially every
professional. Now `require_auth_or_care_bearer`:

  * a bearer with NO eps users row (transient actor) is scoped by its sso
    affiliations: SU = every patient; a professional = patients ACTIVELY
    assigned to an active clinic whose care unit is in
    `affiliations[].care_unit_guid` (never `organization_ids`). Out of scope ->
    the same 404 as "no such patient";
  * a bearer WITH an eps users row keeps its eps-local scope
    (UserClinicAssignment for /state; /clinics unscoped) — unchanged;
  * ApiKey — unchanged.

AUTH ON throughout; only the outbound sso call (`httpx.get`) is patched.
No personnummer is used.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.user import User
from app.services.auth_service import hash_api_key

SSO = "https://sso.test"
UNIT_A = "aaaa1050-0000-4000-8000-0000000000a7"
UNIT_B = "aaaa1050-0000-4000-8000-0000000000b7"
UNIT_GONE = "aaaa1050-0000-4000-8000-0000000000c7"   # inactive clinic


def _blob(kind):
    b = {"user_guid": str(uuid.uuid4()), "email": f"{kind}@example.test",
         "user_type": "professional", "is_su_admin": False,
         "session_phases": [], "affiliations": []}
    aff = {"pro_a": [UNIT_A.upper()], "pro_gone": [UNIT_GONE], "row_a": [UNIT_A],
           "patient": [UNIT_A], "must_change": [UNIT_A]}.get(kind, [])
    b["affiliations"] = [{"care_unit_guid": u, "role": "nurse"} for u in aff]
    if kind == "su":
        b["is_su_admin"] = True
    if kind == "patient":
        b["user_type"] = "patient"
    if kind == "legacy_member":
        b["organization_ids"] = [UNIT_A, UNIT_B]
    if kind == "must_change":
        b["must_change_password"] = True
    return b


KINDS = ("pro_a", "pro_gone", "row_a", "su", "patient", "legacy_member", "must_change")


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeSso:
    def __init__(self):
        self.blobs = {k: _blob(k) for k in KINDS}

    def __call__(self, url, headers=None, timeout=None, **kw):
        assert url.startswith(SSO + "/api/auth/me"), url
        tok = (headers or {}).get("Authorization", "")[len("Bearer tok-"):]
        return _Resp(200, self.blobs[tok]) if tok in self.blobs else _Resp(401, {"error": "x"})


def H(kind):
    return {"Authorization": f"Bearer tok-{kind}"}


@pytest.fixture
def api(client):
    cfg = {"AUTH_DISABLED": False, "OAUTH_BASE_URL": SSO,
           "SSO_CLIENT_ID": "eps-test", "SSO_CLIENT_SECRET": "eps-test-secret"}
    with patch.dict(client.application.config, cfg), \
            patch("app.services.auth_service.httpx.get", FakeSso()):
        yield client


def _patient(db, family):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     given_name="Synt", family_name=family)
    db.session.add(p)
    db.session.flush()
    return p


@pytest.fixture
def world(db):
    a = Clinic(name="Enhet A", organisation_guid=UNIT_A, is_active=True)
    b = Clinic(name="Enhet B", organisation_guid=UNIT_B, is_active=True)
    gone = Clinic(name="Nedlagd", organisation_guid=UNIT_GONE, is_active=False)
    db.session.add_all([a, b, gone])
    db.session.flush()
    pa, pb, pg = _patient(db, "Alfasson"), _patient(db, "Betasson"), _patient(db, "Gonesson")
    db.session.add_all([PatientClinicAssignment(patient_guid=pa.guid, clinic_guid=a.guid),
                        PatientClinicAssignment(patient_guid=pb.guid, clinic_guid=b.guid),
                        PatientClinicAssignment(patient_guid=pg.guid, clinic_guid=gone.guid)])
    # an eps users row whose eps-local assignment is B, while sso says A
    row = User(username="row_a@example.test", is_active=True)
    db.session.add(row)
    db.session.flush()
    db.session.add(UserClinicAssignment(user_guid=row.guid, clinic_guid=b.guid))
    db.session.commit()
    return {"pa": str(pa.guid), "pb": str(pb.guid), "pg": str(pg.guid),
            "pa_rid": pa.resource_id}


def _key(db):
    raw = "invitekey-" + uuid.uuid4().hex
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="svc", prefix=raw[:8],
                          scopes=[], is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


def S(g):
    return f"/api/v1/patients/{g}/state"


def C(g):
    return f"/api/v1/patients/{g}/clinics"


NOBODY = str(uuid.uuid4())


# ---------------------------------------------------------------- /state

def test_state_affiliated_professional_without_eps_row_gets_the_patient(api, db, world):
    r = api.get(S(world["pa"]), headers=H("pro_a"))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["patient_guid"] == world["pa"]


def test_state_other_unit_is_the_same_404_as_nobody(api, db, world):
    other = api.get(S(world["pb"]), headers=H("pro_a"))
    nobody = api.get(S(NOBODY), headers=H("pro_a"))
    assert other.status_code == nobody.status_code == 404
    assert other.get_json() == nobody.get_json()


def test_state_su_without_eps_row_reads_any_patient(api, db, world):
    for p in ("pa", "pb", "pg"):
        assert api.get(S(world[p]), headers=H("su")).status_code == 200


def test_state_memberships_are_not_affiliations(api, db, world):
    assert api.get(S(world["pa"]), headers=H("legacy_member")).status_code == 404


def test_state_inactive_clinic_does_not_scope(api, db, world):
    assert api.get(S(world["pg"]), headers=H("pro_gone")).status_code == 404


def test_state_patient_bearer_and_must_change_are_refused(api, db, world):
    assert api.get(S(world["pa"]), headers=H("patient")).status_code == 401
    assert api.get(S(world["pa"]), headers=H("must_change")).status_code in (401, 403)
    assert api.get(S(world["pa"]), headers=H("nobody")).status_code == 401


def test_state_eps_users_row_keeps_its_eps_local_scope(api, db, world):
    # sso says A, eps-local assignment says B: the eps row decides, as before.
    assert api.get(S(world["pb"]), headers=H("row_a")).status_code == 200
    assert api.get(S(world["pa"]), headers=H("row_a")).status_code == 404


def test_state_apikey_unchanged(api, db, world):
    # an identity-less service key has no clinic assignments: 404, as before
    h = _key(db)
    assert api.get(S(world["pa"]), headers=h).status_code == 404
    assert api.get(S(world["pa"]), headers={"X-API-Key": "x"}).status_code == 401


# ---------------------------------------------------------------- /clinics

def test_clinics_affiliated_professional_without_eps_row(api, db, world):
    r = api.get(C(world["pa"]), headers=H("pro_a"))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [c["care_unit_guid"] for c in r.get_json()] == [UNIT_A]
    assert r.headers["X-PDHC-Patient-Guid"] == world["pa"]
    # by FHIR resource_id too, naming the platform guid
    r = api.get(C(world["pa_rid"]), headers=H("pro_a"))
    assert r.status_code == 200 and r.headers["X-PDHC-Patient-Guid"] == world["pa"]


def test_clinics_other_unit_is_the_same_404_as_nobody(api, db, world):
    other = api.get(C(world["pb"]), headers=H("pro_a"))
    nobody = api.get(C(NOBODY), headers=H("pro_a"))
    assert other.status_code == nobody.status_code == 404
    assert other.get_json() == nobody.get_json()
    assert "X-PDHC-Patient-Guid" not in other.headers


def test_clinics_su_without_eps_row_reads_any_patient(api, db, world):
    for p in ("pa", "pb"):
        assert api.get(C(world[p]), headers=H("su")).status_code == 200


def test_clinics_memberships_are_not_affiliations(api, db, world):
    assert api.get(C(world["pa"]), headers=H("legacy_member")).status_code == 404


def test_clinics_eps_users_row_and_apikey_unchanged_unscoped(api, db, world):
    # before #1050 neither path scoped /clinics; still true
    assert api.get(C(world["pa"]), headers=H("row_a")).status_code == 200
    h = _key(db)
    for p in ("pa", "pb"):
        r = api.get(C(world[p]), headers=h)
        assert r.status_code == 200
        assert r.headers["X-PDHC-Patient-Guid"] == world[p]
    assert api.get(C(NOBODY), headers=h).status_code == 404
    assert api.get(C(world["pa"]), headers={"X-API-Key": "x"}).status_code == 401
