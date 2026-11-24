"""#1045 loggkontroll: one patient's access log from eps, for a PERSON.

    GET /api/v1/audit/patients/<guid>
    GET /api/v1/audit                 (now SU only)

AUTH ON throughout; only the outbound sso call (`httpx.get`) is patched, as in
test_invite_reads_bearer_1050. No personnummer is used.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_log import AuditLog
from tests.test_invite_reads_bearer_1050 import (  # noqa: F401 — fixtures
    H, NOBODY, _key, api, world)


def L(g, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return f"/api/v1/audit/patients/{g}" + (f"?{qs}" if qs else "")


def _row(db, patient, event, at, **kw):
    r = AuditLog(patient_guid=uuid.UUID(patient), event_type=event,
                 actor_guid=uuid.uuid4(), actor_type="user",
                 actor_label="kollega@example.test", request_method="GET",
                 request_path=f"/api/v1/patients/{patient}/state",
                 created_at=at, **kw)
    db.session.add(r)
    db.session.commit()
    return r


T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def logged(db, world):
    _row(db, world["pa"], "euips_summary_read", T0,
         detail={"reason": "vård", "clinical": "MUST NOT LEAK"})
    _row(db, world["pa"], "fhir_update", T0 + timedelta(days=2))
    _row(db, world["pb"], "euips_summary_read", T0)
    return world


def _events(db, patient, event):
    return db.session.query(AuditLog).filter_by(
        patient_guid=uuid.UUID(patient), event_type=event).count()


def test_affiliated_professional_reads_the_patients_log(api, db, logged):
    r = api.get(L(logged["pa"]), headers=H("pro_a"))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["service"] == "eps.pdhc" and body["patient_guid"] == logged["pa"]
    assert [i["action"] for i in body["items"]] == ["euips_summary_read", "fhir_update"]
    first = body["items"][0]
    assert first["user_label"] == "kollega@example.test"
    assert first["route"].startswith("GET /api/v1/patients/")
    assert first["detail"] == {"reason": "vård"}          # whitelist only
    assert "MUST NOT LEAK" not in r.get_data(as_text=True)
    assert body["truncated"] is False


def test_the_read_of_the_log_is_itself_logged(api, db, logged):
    assert _events(db, logged["pa"], "patient.access_log.read") == 0
    api.get(L(logged["pa"]), headers=H("pro_a"))
    assert _events(db, logged["pa"], "patient.access_log.read") == 1


def test_other_unit_is_the_same_404_as_nobody_and_is_logged(api, db, logged):
    other = api.get(L(logged["pb"]), headers=H("pro_a"))
    nobody = api.get(L(NOBODY), headers=H("pro_a"))
    assert other.status_code == nobody.status_code == 404
    assert other.get_json() == nobody.get_json()
    assert _events(db, logged["pb"], "patient.access_log.refused") == 1
    assert _events(db, logged["pb"], "patient.access_log.read") == 0


def test_su_reads_any_patient(api, db, logged):
    assert api.get(L(logged["pb"]), headers=H("su")).status_code == 200


def test_memberships_and_inactive_units_do_not_scope(api, db, logged):
    assert api.get(L(logged["pa"]), headers=H("legacy_member")).status_code == 404
    assert api.get(L(logged["pg"]), headers=H("pro_gone")).status_code == 404


def test_a_service_key_is_refused_by_name(api, db, logged):
    r = api.get(L(logged["pa"]), headers=_key(db))
    assert r.status_code == 403
    assert r.get_json()["error"] == "bearer_required"


def test_patient_bearer_and_unknown_token_are_refused(api, db, logged):
    assert api.get(L(logged["pa"]), headers=H("patient")).status_code == 401
    assert api.get(L(logged["pa"]), headers=H("nobody")).status_code == 401


def test_date_range_and_limit(api, db, logged):
    r = api.get(L(logged["pa"], **{"from": "2026-11-02T00:00:00Z"}), headers=H("su"))
    assert [i["action"] for i in r.get_json()["items"]] == ["fhir_update"]
    r = api.get(L(logged["pa"], to="2026-11-02T00:00:00Z"), headers=H("su"))
    assert [i["action"] for i in r.get_json()["items"]] == ["euips_summary_read"]
    r = api.get(L(logged["pa"], limit=1), headers=H("su"))
    assert len(r.get_json()["items"]) == 1 and r.get_json()["truncated"] is True
    assert api.get(L(logged["pa"], to="igår"), headers=H("su")).status_code == 400


def test_whole_log_is_su_only(api, db, logged):
    # an eps users row that is not superuser, and a service key: both were
    # admitted organisation-blind before #1045
    assert api.get("/api/v1/audit", headers=H("row_a")).status_code == 403
    assert api.get("/api/v1/audit", headers=_key(db)).status_code == 403


def test_whole_log_still_serves_a_superuser(client, db, logged):
    # AUTH_DISABLED's dev user is superuser (the existing TestAppAuditLog path)
    r = client.get("/api/v1/audit")
    assert r.status_code == 200 and len(r.get_json()) >= 3
