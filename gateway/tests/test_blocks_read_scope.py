"""A filtering service (gateway's observation filter) must be able to read a
patient's blocks. Its key has no user, so the per-clinic rule refused it for
every patient, and its client read "blocks" where the answer said "items":
either way the filter saw no blocks and let everything through.

AUTH ON, a real key, the real route -- under AUTH_DISABLED the gate does not run.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import hash_api_key

SCOPE = "blocks:read"   # literal: the control must fail on the assertion


def _key(db, scopes):
    raw = f"kblk-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="blocks key",
                          prefix=raw[:8], scopes=scopes, is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


@pytest.fixture
def blocked(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir); db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     family_name="Synthetic", given_name="Test")
    clinic = Clinic(name=f"blk clinic {uuid.uuid4().hex[:6]}", is_active=True)
    db.session.add_all([p, clinic]); db.session.flush()
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=clinic.guid))
    b = PatientBlock(patient_guid=p.guid, source_scope_type="clinic",
                     source_scope_id=clinic.guid, created_reason="test")
    db.session.add(b); db.session.commit()
    return p, clinic


@pytest.fixture
def auth_on(client):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
        yield client


def _url(p):
    return f"/api/v1/patients/{p.guid}/blocks"


def test_scoped_key_reads_the_block_unredacted(auth_on, db, blocked):
    p, clinic = blocked
    r = auth_on.get(_url(p), headers=_key(db, [SCOPE]))
    assert r.status_code == 200, r.get_data(as_text=True)
    items = r.get_json()["items"]
    assert len(items) == 1
    assert items[0]["source_scope_id"] == str(clinic.guid)   # a filter needs it
    assert items[0]["is_active"] is True and items[0]["redacted"] is False


def test_answer_also_carries_blocks_for_the_existing_clients(auth_on, db, blocked):
    p, _ = blocked
    body = auth_on.get(_url(p), headers=_key(db, [SCOPE])).get_json()
    assert body["blocks"] == body["items"] and len(body["blocks"]) == 1


def test_unscoped_and_other_scoped_keys_stay_refused(auth_on, db, blocked):
    p, _ = blocked
    assert auth_on.get(_url(p), headers=_key(db, [])).status_code == 403
    assert auth_on.get(_url(p), headers=_key(db, ["consents:emit"])).status_code == 403


@pytest.mark.parametrize("bad", ["blocks:read", {"blocks:read": True}])
def test_malformed_scopes_value_denies(auth_on, db, blocked, bad):
    p, _ = blocked
    assert auth_on.get(_url(p), headers=_key(db, bad)).status_code == 403


def test_scope_is_read_only_and_opens_nothing_else(auth_on, db, blocked):
    p, clinic = blocked
    h = _key(db, [SCOPE])
    w = auth_on.post(_url(p), headers=h, json={"source_scope_type": "clinic",
                     "source_scope_id": str(clinic.guid), "reason": "x"})
    assert w.status_code == 403
    assert auth_on.get(f"/api/v1/patients/{p.guid}/consents", headers=h).status_code == 403


def test_junk_key_is_401(auth_on, db, blocked):
    p, _ = blocked
    assert auth_on.get(_url(p), headers={"Authorization": "ApiKey junk"}).status_code == 401
