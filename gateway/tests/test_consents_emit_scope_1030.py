"""#1030 — contract.pdhc's consent emitter was refused for EVERY patient.

Its key carries ``consents:emit`` and no user, so ips gave it a transient
service-account user with no clinic, and the per-clinic rule refused list,
grant and revoke alike (403). The scope was never read.

These tests run with AUTH ON and a real API key through the real routes,
because the rest of the consent suite runs under AUTH_DISABLED, where the
gate under test does not execute at all.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import hash_api_key

# Literal on purpose: the control (fix reverted) must fail on the assertion,
# not on an import of the new constant.
SCOPE_CONSENTS_EMIT = "consents:emit"


def _key(db, scopes):
    raw = f"k1030-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="1030 key",
                          prefix=raw[:8], scopes=scopes, is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


@pytest.fixture
def patient(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir); db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     family_name="Synthetic", given_name="Test")
    clinic = Clinic(name=f"1030 clinic {uuid.uuid4().hex[:6]}", is_active=True)
    db.session.add_all([p, clinic]); db.session.flush()
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=clinic.guid))
    db.session.commit()
    return p


@pytest.fixture
def auth_on(client):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
        yield client


def _grant(c, p, h):
    return c.post(f"/api/v1/patients/{p.guid}/consents", headers=h,
                  json={"grantee_caregiver_guid": str(uuid.uuid4()),
                        "granted_via": "contract"})


class TestTheEmitterKey:
    def test_scoped_key_can_list(self, auth_on, db, patient):
        r = auth_on.get(f"/api/v1/patients/{patient.guid}/consents",
                        headers=_key(db, [SCOPE_CONSENTS_EMIT]))
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_scoped_key_can_grant_then_revoke(self, auth_on, db, patient):
        h = _key(db, [SCOPE_CONSENTS_EMIT])
        g = _grant(auth_on, patient, h)
        assert g.status_code == 201, g.get_data(as_text=True)
        cg = g.get_json()["guid"]
        r = auth_on.post(f"/api/v1/patients/{patient.guid}/consents/{cg}/revoke",
                         headers=h, json={"reason": "1030 test"})
        assert r.status_code == 200, r.get_data(as_text=True)


class TestTheScopeOpensNothingElse:
    def test_unscoped_key_is_still_refused(self, auth_on, db, patient):
        r = auth_on.get(f"/api/v1/patients/{patient.guid}/consents",
                        headers=_key(db, []))
        assert r.status_code == 403

    def test_other_scope_is_still_refused(self, auth_on, db, patient):
        r = _grant(auth_on, patient, _key(db, ["implants:write"]))
        assert r.status_code == 403

    @pytest.mark.parametrize("bad", ["consents:emit", {"consents:emit": True}])
    def test_malformed_scopes_value_denies(self, auth_on, db, patient, bad):
        # a STRING must not match by substring (#804 shape)
        r = auth_on.get(f"/api/v1/patients/{patient.guid}/consents",
                        headers=_key(db, bad))
        assert r.status_code == 403

    def test_scope_does_not_open_blocks(self, auth_on, db, patient):
        r = auth_on.get(f"/api/v1/patients/{patient.guid}/blocks",
                        headers=_key(db, [SCOPE_CONSENTS_EMIT]))
        assert r.status_code == 403, r.status_code

    def test_junk_key_is_401(self, auth_on, db, patient):
        r = auth_on.get(f"/api/v1/patients/{patient.guid}/consents",
                        headers={"Authorization": "ApiKey junk"})
        assert r.status_code == 401
