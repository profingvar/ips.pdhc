"""#1050: patients join the patient app ONLY by invitation from their unit.

Two eps routes:

  POST /api/v1/patients/register-at-unit         dashboard, the PROFESSIONAL'S
                                                 own SSO bearer
  POST /api/v1/patients/<guid>/identifier-match  sso's invite page, its eps key
                                                 with scope patients:identifier-match

AUTH ON throughout (AUTH_DISABLED would skip every gate tested here). The ONLY
thing patched is the outbound HTTP call to sso (`httpx.get` in auth_service),
answered by a fake sso that knows one bearer per blob. Personnummer are
SYNTHETIC (build_synthetic: wrong check digit) and are never printed.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import personnummer as pnr
from app.services.auth_service import hash_api_key

URL = "/api/v1/patients/register-at-unit"
MATCH_SCOPE = "patients:identifier-match"   # literal: a control must fail on the assertion
SSO = "https://sso.test"

UNIT_A = "aaaa1050-0000-4000-8000-00000000000a"
UNIT_B = "aaaa1050-0000-4000-8000-00000000000b"


def _blob(kind):
    base = {"user_guid": str(uuid.uuid4()), "email": f"{kind}@example.test",
            "user_type": "professional", "is_su_admin": False,
            "session_phases": [], "effective_phases": [], "affiliations": []}
    if kind == "pro_a":
        base["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"}]
    elif kind == "pro_ab":
        base["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"},
                                {"care_unit_guid": UNIT_B, "role": "doctor"}]
    elif kind == "pro_b":
        base["affiliations"] = [{"care_unit_guid": UNIT_B, "role": "nurse"}]
    elif kind == "su":
        base["is_su_admin"] = True
    elif kind == "patient":
        base["user_type"] = "patient"
        base["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"}]
    elif kind == "legacy_member":
        # a membership (organization_ids) but NO affiliation: not enough
        base["organization_ids"] = [UNIT_A]
    elif kind == "must_change":
        base["affiliations"] = [{"care_unit_guid": UNIT_A, "role": "nurse"}]
        base["must_change_password"] = True
    return base


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeSso:
    """sso's /api/auth/me/service: `Bearer tok-<kind>` -> that blob."""

    def __init__(self):
        self.blobs = {k: _blob(k) for k in ("pro_a", "pro_ab", "pro_b", "su", "patient",
                                             "legacy_member", "must_change")}
        self.calls = []

    def __call__(self, url, headers=None, timeout=None, **kw):
        self.calls.append(url)
        assert url.startswith(SSO + "/api/auth/me"), url
        tok = (headers or {}).get("Authorization", "")[len("Bearer tok-"):]
        if tok in self.blobs:
            return _Resp(200, self.blobs[tok])
        return _Resp(401, {"error": "invalid"})


def H(kind):
    return {"Authorization": f"Bearer tok-{kind}"}


@pytest.fixture
def sso():
    return FakeSso()


@pytest.fixture
def api(client, sso):
    cfg = {"AUTH_DISABLED": False, "OAUTH_BASE_URL": SSO,
           "SSO_CLIENT_ID": "eps-test", "SSO_CLIENT_SECRET": "eps-test-secret"}
    with patch.dict(client.application.config, cfg), \
            patch("app.services.auth_service.httpx.get", sso):
        yield client


@pytest.fixture
def clinics(db):
    a = Clinic(name="Enhet A", organisation_guid=UNIT_A, is_active=True)
    b = Clinic(name="Enhet B", organisation_guid=UNIT_B, is_active=True)
    db.session.add_all([a, b]); db.session.commit()
    return a, b


def _pnr(serial=321):
    return pnr.build_synthetic(date(1979, 5, 17), serial)


def _body(**over):
    b = {"given_name": "Synt", "family_name": "Inbjudensson",
         "personnummer": _pnr(), "care_unit_guid": UNIT_A, "mobile": "+46700000001"}
    b.update(over)
    return b


def _assignments(db, guid):
    return db.session.query(PatientClinicAssignment).filter_by(
        patient_guid=uuid.UUID(guid)).all()


# --------------------------------------------------------------------------
# register-at-unit
# --------------------------------------------------------------------------

def test_creates_patient_with_invited_assignment(api, db, clinics):
    a, _ = clinics
    r = api.post(URL, json=_body(), headers=H("pro_a"))
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    assert body["created"] is True and body["assignment"] == "added"
    guid = body["patient_guid"]
    assert r.headers["X-PDHC-Patient-Guid"] == guid
    p = db.session.get(PatientIndex, uuid.UUID(guid))
    assert p.resource_id == guid
    assert p.identifier_value == pnr.normalise(_pnr())
    assert (p.given_name, p.family_name) == ("Synt", "Inbjudensson")
    rows = _assignments(db, guid)
    assert len(rows) == 1 and rows[0].clinic_guid == a.guid
    assert rows[0].origin == "invited" and rows[0].ended_at is None
    fhir = db.session.query(FhirResource).filter_by(resource_type="Patient",
                                                    resource_id=guid).one()
    assert fhir.resource_json["telecom"] == [
        {"system": "phone", "value": "+46700000001", "use": "mobile"}]
    # sso's verify_patient reads /clinics: the new patient is listed there
    with patch.dict(api.application.config, {"AUTH_DISABLED": True}):
        listed = api.get(f"/api/v1/patients/{guid}/clinics").get_json()
    assert [c["care_unit_guid"] for c in listed] == [UNIT_A]


def test_existing_patient_is_found_by_either_spelling_and_given_the_unit(api, db, clinics):
    a, b = clinics
    first = api.post(URL, json=_body(care_unit_guid=UNIT_B), headers=H("pro_b"))
    assert first.status_code == 201
    guid = first.get_json()["patient_guid"]
    # 12 digits, no dash, other case and spacing of the name: the same person
    r = api.post(URL, json=_body(personnummer=_pnr().replace("-", ""),
                                 given_name="  SYNT ", family_name="inbjudensson"),
                 headers=H("pro_a"))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {"patient_guid": guid, "created": False, "assignment": "added"}
    units = {row.clinic_guid: row.origin for row in _assignments(db, guid)}
    assert units == {a.guid: "invited", b.guid: "invited"}
    assert db.session.query(PatientIndex).count() == 1
    # again: the open assignment is there already and is left alone
    r = api.post(URL, json=_body(), headers=H("pro_a"))
    assert r.status_code == 200 and r.get_json()["assignment"] == "existing"
    assert len(_assignments(db, guid)) == 2


def test_an_existing_assignment_keeps_its_origin(api, db, clinics):
    a, _ = clinics
    guid = api.post(URL, json=_body(), headers=H("pro_a")).get_json()["patient_guid"]
    row = _assignments(db, guid)[0]
    row.origin = None; db.session.commit()
    assert api.post(URL, json=_body(), headers=H("pro_a")).get_json()["assignment"] == "existing"
    assert _assignments(db, guid)[0].origin is None


def test_an_ENDED_assignment_is_reopened_as_a_new_row(api, db, clinics):
    guid = api.post(URL, json=_body(), headers=H("pro_a")).get_json()["patient_guid"]
    row = _assignments(db, guid)[0]
    row.ended_at = datetime(2026, 1, 1, tzinfo=timezone.utc); db.session.commit()
    r = api.post(URL, json=_body(), headers=H("pro_a"))
    assert r.status_code == 200 and r.get_json()["assignment"] == "added"
    rows = _assignments(db, guid)
    assert len(rows) == 2 and sum(1 for x in rows if x.ended_at is None) == 1


def test_name_mismatch_writes_nothing(api, db, clinics):
    first = api.post(URL, json=_body(care_unit_guid=UNIT_B), headers=H("pro_b"))
    guid = first.get_json()["patient_guid"]
    r = api.post(URL, json=_body(given_name="Annan"), headers=H("pro_a"))
    assert r.status_code == 409 and r.get_json() == {"error": "name_mismatch"}
    assert "X-PDHC-Patient-Guid" not in r.headers
    assert len(_assignments(db, guid)) == 1          # NOT attached to unit A
    r = api.post(URL, json=_body(family_name="Annansson"), headers=H("pro_a"))
    assert r.status_code == 409 and r.get_json() == {"error": "name_mismatch"}


def test_archived_and_ambiguous_are_refused(api, db, clinics):
    guid = api.post(URL, json=_body(), headers=H("pro_a")).get_json()["patient_guid"]
    p = db.session.get(PatientIndex, uuid.UUID(guid))
    p.archived_at = datetime.now(timezone.utc); db.session.commit()
    r = api.post(URL, json=_body(), headers=H("pro_a"))
    assert r.status_code == 409 and r.get_json() == {"error": "archived"}
    # a second record carrying the same number in the other spelling
    rid = str(uuid.uuid4())
    f = FhirResource(resource_type="Patient", resource_id=rid,
                     resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(f); db.session.flush()
    db.session.add(PatientIndex(fhir_resource_guid=f.guid, resource_id=rid,
                                identifier_value=_pnr().replace("-", ""),
                                given_name="Synt", family_name="Inbjudensson"))
    db.session.commit()
    r = api.post(URL, json=_body(), headers=H("pro_a"))
    assert r.status_code == 409 and r.get_json() == {"error": "ambiguous"}


def test_who_may_register_at_a_unit(api, db, clinics):
    assert api.post(URL, json=_body(), headers=H("pro_a")).status_code == 201
    assert api.post(URL, json=_body(personnummer=_pnr(322)),
                    headers=H("pro_ab")).status_code == 201
    assert api.post(URL, json=_body(personnummer=_pnr(323)),
                    headers=H("su")).status_code == 201
    n = db.session.query(PatientIndex).count()
    # affiliated to ANOTHER unit
    r = api.post(URL, json=_body(personnummer=_pnr(324)), headers=H("pro_b"))
    assert r.status_code == 403 and r.get_json()["error"] == "not_affiliated"
    # a membership is not an affiliation (CLAUDE.md s11, 2026-11-14)
    r = api.post(URL, json=_body(personnummer=_pnr(325)), headers=H("legacy_member"))
    assert r.status_code == 403 and r.get_json()["error"] == "not_affiliated"
    # a patient blob, even one that somehow carries an affiliation
    r = api.post(URL, json=_body(personnummer=_pnr(326)), headers=H("patient"))
    assert r.status_code == 403 and r.get_json()["error"] == "not_professional"
    r = api.post(URL, json=_body(personnummer=_pnr(327)), headers=H("must_change"))
    assert r.status_code == 403
    assert api.post(URL, json=_body(personnummer=_pnr(328)),
                    headers={"Authorization": "Bearer tok-unknown"}).status_code == 401
    assert api.post(URL, json=_body(personnummer=_pnr(329))).status_code == 401
    assert db.session.query(PatientIndex).count() == n


def test_not_affiliated_is_answered_before_any_lookup(api, db, clinics):
    """An outsider learns nothing: an existing number, a mismatching name and
    a real-format number all get the same 403."""
    api.post(URL, json=_body(), headers=H("pro_a"))
    for body in (_body(), _body(given_name="X"),
                 _body(personnummer=pnr.build(date(1979, 5, 17), 321))):
        r = api.post(URL, json=body, headers=H("pro_b"))
        assert r.status_code == 403 and r.get_json()["error"] == "not_affiliated"


def test_a_service_key_is_refused_even_with_every_scope(api, db, clinics):
    raw = f"k-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="svc", prefix=raw[:8],
                          scopes=["patients:self-register", MATCH_SCOPE], is_active=True))
    db.session.commit()
    r = api.post(URL, json=_body(), headers={"Authorization": f"ApiKey {raw}"})
    assert r.status_code == 403
    assert db.session.query(PatientIndex).count() == 0


def test_real_and_malformed_personnummer_and_validation(api, db, clinics):
    real_shape = pnr.build(date(1979, 5, 17), 321)          # VALID check digit
    r = api.post(URL, json=_body(personnummer=real_shape), headers=H("pro_a"))
    assert r.status_code == 422 and r.get_json() == {"error": "real_personnummer"}
    r = api.post(URL, json=_body(personnummer="19790231-1234"), headers=H("pro_a"))
    assert r.status_code == 422 and r.get_json() == {"error": "invalid_personnummer"}
    r = api.post(URL, json={"care_unit_guid": UNIT_A, "personnummer": _pnr()},
                 headers=H("pro_a"))
    assert r.status_code == 422
    assert r.get_json() == {"error": "validation", "fields": ["family_name", "given_name"]}
    assert db.session.query(PatientIndex).count() == 0


def test_unknown_or_inactive_unit(api, db, clinics):
    a, _ = clinics
    a.is_active = False; db.session.commit()
    r = api.post(URL, json=_body(), headers=H("pro_a"))
    assert r.status_code == 422 and r.get_json() == {"error": "unknown_unit"}
    # an SU naming a unit no eps clinic is
    r = api.post(URL, json=_body(care_unit_guid=str(uuid.uuid4())), headers=H("su"))
    assert r.status_code == 422 and r.get_json() == {"error": "unknown_unit"}


def test_audited_as_the_professional_without_the_personnummer(api, db, clinics, sso):
    guid = api.post(URL, json=_body(), headers=H("pro_a")).get_json()["patient_guid"]
    rows = db.session.query(AuditLog).filter_by(event_type="patient_registered_at_unit").all()
    assert len(rows) == 1 and str(rows[0].patient_guid) == guid
    assert str(rows[0].actor_guid) == sso.blobs["pro_a"]["user_guid"]
    assert rows[0].actor_type == "user"
    digits = pnr.normalise(_pnr()).replace("-", "")
    for row in db.session.query(AuditLog).all():
        assert digits[2:] not in str(row.detail).replace("-", "")
    api.post(URL, json=_body(given_name="Fel"), headers=H("pro_a"))
    refused = db.session.query(AuditLog).filter_by(
        event_type="patient_register_at_unit_refused").one()
    assert refused.detail["reason"] == "name_mismatch"


# --------------------------------------------------------------------------
# identifier-match (sso's invite page)
# --------------------------------------------------------------------------

def _key(db, scopes):
    raw = f"kmatch-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="sso", prefix=raw[:8],
                          scopes=scopes, is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


def test_identifier_match_yes_and_no(api, db, clinics):
    guid = api.post(URL, json=_body(), headers=H("pro_a")).get_json()["patient_guid"]
    h = _key(db, [MATCH_SCOPE])
    m = f"/api/v1/patients/{guid}/identifier-match"
    r = api.post(m, json={"personnummer": _pnr().replace("-", "")}, headers=h)
    assert r.status_code == 200 and r.get_json() == {"match": True}
    r = api.post(m, json={"personnummer": _pnr()}, headers=h)
    assert r.get_json() == {"match": True}
    r = api.post(m, json={"personnummer": _pnr(999)}, headers=h)
    assert r.status_code == 200 and r.get_json() == {"match": False}
    r = api.post(m, json={"personnummer": "nonsense"}, headers=h)
    assert r.status_code == 422 and r.get_json() == {"error": "invalid_personnummer"}
    r = api.post(f"/api/v1/patients/{uuid.uuid4()}/identifier-match",
                 json={"personnummer": _pnr()}, headers=h)
    assert r.status_code == 404 and r.get_json() == {"error": "Patient not found"}
    rows = db.session.query(AuditLog).filter_by(event_type="patient_identifier_match").all()
    assert [x.detail["match"] for x in rows] == [True, True, False]
    digits = pnr.normalise(_pnr()).replace("-", "")
    assert all(digits[2:] not in str(x.detail) for x in rows)


def test_identifier_match_needs_the_scope(api, db, clinics):
    guid = api.post(URL, json=_body(), headers=H("pro_a")).get_json()["patient_guid"]
    m = f"/api/v1/patients/{guid}/identifier-match"
    for scopes in ([], ["patients:self-register"], MATCH_SCOPE):
        r = api.post(m, json={"personnummer": _pnr()}, headers=_key(db, scopes))
        assert r.status_code == 403, scopes
    # a professional's bearer is not a key: refused too, SU included
    assert api.post(m, json={"personnummer": _pnr()}, headers=H("su")).status_code in (401, 403)
