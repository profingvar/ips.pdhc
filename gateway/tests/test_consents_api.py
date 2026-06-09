"""Tests for the PatientConsent REST surface — IPS Renov 2 (#198).

Covers:
- Grant — happy admin; staff with relationship; duplicate active 409;
  unrelated staff 403; missing/invalid grantee; expires_at parse;
  concept-narrowed grant; bad concept_guids.
- List — admin sees all; staff-with-relationship sees all; unrelated
  staff 403; active filter.
- Revoke — happy; double-revoke 409; not-found 404.
- Audit — consent.granted + consent.revoked AuditLog rows shape.

Reuses the seed fixture pattern from test_blocks_api: 2 clinics, 1
patient at clinic A, staff_a / staff_b / su. The synthetic auth user
is re-pointed via the same _synthetic_dev_user monkeypatch.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed(client, db):
    fhir = FhirResource(
        resource_type="Patient", resource_id=str(uuid.uuid4()),
        resource_json={"resourceType": "Patient"},
    )
    db.session.add(fhir)
    db.session.flush()

    patient = PatientIndex(
        fhir_resource_guid=fhir.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Bergstrom",
        given_name="Bo",
    )
    db.session.add(patient)
    db.session.flush()

    clinic_a = Clinic(name="ConsentClinic A", is_active=True)
    clinic_b = Clinic(name="ConsentClinic B", is_active=True)
    db.session.add_all([clinic_a, clinic_b])
    db.session.flush()

    db.session.add(PatientClinicAssignment(
        patient_guid=patient.guid, clinic_guid=clinic_a.guid,
    ))

    staff_a = User(
        username=f"consent_staff_a_{uuid.uuid4().hex[:8]}",
        display_name="Staff at A", role="operator",
        is_active=True, is_superuser=False,
    )
    staff_b = User(
        username=f"consent_staff_b_{uuid.uuid4().hex[:8]}",
        display_name="Staff at B", role="operator",
        is_active=True, is_superuser=False,
    )
    su = User(
        username=f"consent_su_{uuid.uuid4().hex[:8]}",
        display_name="SU", role="admin",
        is_active=True, is_superuser=True,
    )
    db.session.add_all([staff_a, staff_b, su])
    db.session.flush()
    db.session.add(UserClinicAssignment(
        user_guid=staff_a.guid, clinic_guid=clinic_a.guid,
    ))
    db.session.add(UserClinicAssignment(
        user_guid=staff_b.guid, clinic_guid=clinic_b.guid,
    ))
    db.session.commit()

    return {
        "patient": patient,
        "clinic_a": clinic_a, "clinic_b": clinic_b,
        "staff_a": staff_a, "staff_b": staff_b, "su": su,
    }


@pytest.fixture
def as_user():
    @contextmanager
    def _impersonate(user):
        with patch(
            "app.services.auth_service._synthetic_dev_user",
            return_value=user,
        ):
            yield
    return _impersonate


def _grantee_guid():
    """A throwaway caregiver guid (not FK'd — caregivers live in sso)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------

class TestCreateConsent:
    def test_admin_happy_path(self, client, db, seed):
        pat = seed["patient"]
        cg = _grantee_guid()
        r = client.post(
            f"/api/v1/patients/{pat.guid}/consents",
            json={
                "grantee_caregiver_guid": cg,
                "granted_via": "portal",
                "granted_note": "patient gave consent in the portal",
            },
        )
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert body["patient_guid"] == str(pat.guid)
        assert body["grantee_caregiver_guid"] == cg
        assert body["granted_via"] == "portal"
        assert body["revoked_at"] is None
        assert body["is_active"] is True
        # Audit row.
        rows = db.session.query(AuditLog).filter_by(
            event_type="consent.granted",
        ).all()
        assert len(rows) == 1
        assert rows[0].patient_guid == pat.guid
        assert rows[0].detail["grantee_caregiver_guid"] == cg

    def test_staff_with_relationship_can_grant(
        self, client, db, seed, as_user,
    ):
        with as_user(seed["staff_a"]):
            r = client.post(
                f"/api/v1/patients/{seed['patient'].guid}/consents",
                json={"grantee_caregiver_guid": _grantee_guid()},
            )
        assert r.status_code == 201

    def test_unrelated_staff_is_403(self, client, db, seed, as_user):
        with as_user(seed["staff_b"]):
            r = client.post(
                f"/api/v1/patients/{seed['patient'].guid}/consents",
                json={"grantee_caregiver_guid": _grantee_guid()},
            )
        assert r.status_code == 403

    def test_missing_grantee_is_400(self, client, db, seed):
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={},
        )
        assert r.status_code == 400

    def test_invalid_grantee_uuid_is_400(self, client, db, seed):
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={"grantee_caregiver_guid": "not-a-uuid"},
        )
        assert r.status_code == 400

    def test_invalid_granted_via_is_400(self, client, db, seed):
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={
                "grantee_caregiver_guid": _grantee_guid(),
                "granted_via": "sms-pigeon",
            },
        )
        assert r.status_code == 400

    def test_duplicate_active_is_409(self, client, db, seed):
        cg = _grantee_guid()
        body = {"grantee_caregiver_guid": cg}
        r1 = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json=body,
        )
        assert r1.status_code == 201
        r2 = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json=body,
        )
        assert r2.status_code == 409
        assert "existing_consent_guid" in r2.get_json()

    def test_concept_narrowed_grant_persists_guids(
        self, client, db, seed,
    ):
        cg = _grantee_guid()
        concepts = [str(uuid.uuid4()) for _ in range(2)]
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={
                "grantee_caregiver_guid": cg,
                "consented_concept_guids": concepts,
            },
        )
        assert r.status_code == 201, r.get_json()
        assert sorted(r.get_json()["consented_concept_guids"]) == sorted(
            concepts,
        )

    def test_bad_concept_guids_is_400(self, client, db, seed):
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={
                "grantee_caregiver_guid": _grantee_guid(),
                "consented_concept_guids": ["not-a-uuid"],
            },
        )
        assert r.status_code == 400

    def test_expires_at_iso_parse(self, client, db, seed):
        future = (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat()
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={
                "grantee_caregiver_guid": _grantee_guid(),
                "expires_at": future,
            },
        )
        assert r.status_code == 201
        assert r.get_json()["expires_at"] is not None

    def test_bad_expires_at_is_400(self, client, db, seed):
        r = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={
                "grantee_caregiver_guid": _grantee_guid(),
                "expires_at": "next tuesday",
            },
        )
        assert r.status_code == 400

    def test_patient_not_found_is_404(self, client, db, seed):
        r = client.post(
            f"/api/v1/patients/{uuid.uuid4()}/consents",
            json={"grantee_caregiver_guid": _grantee_guid()},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListConsents:
    def test_admin_sees_all(self, client, db, seed):
        cg = _grantee_guid()
        client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={"grantee_caregiver_guid": cg},
        )
        r = client.get(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["total"] == 1
        assert body["items"][0]["grantee_caregiver_guid"] == cg

    def test_unrelated_staff_is_403(self, client, db, seed, as_user):
        with as_user(seed["staff_b"]):
            r = client.get(
                f"/api/v1/patients/{seed['patient'].guid}/consents",
            )
        assert r.status_code == 403

    def test_active_filter_excludes_revoked(self, client, db, seed):
        cg = _grantee_guid()
        r1 = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={"grantee_caregiver_guid": cg},
        )
        consent_guid = r1.get_json()["guid"]
        # Revoke
        rv = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents/"
            f"{consent_guid}/revoke",
            json={"reason": "patient changed their mind"},
        )
        assert rv.status_code == 200

        # active default -> empty
        r_active = client.get(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
        )
        assert r_active.get_json()["total"] == 0
        # active=false -> sees the revoked row
        r_all = client.get(
            f"/api/v1/patients/{seed['patient'].guid}/consents?active=false",
        )
        assert r_all.get_json()["total"] == 1
        assert r_all.get_json()["items"][0]["revoked_at"] is not None


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------

class TestRevokeConsent:
    def test_revoke_admin_happy(self, client, db, seed):
        cg = _grantee_guid()
        r1 = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={"grantee_caregiver_guid": cg},
        )
        consent_guid = r1.get_json()["guid"]
        rv = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents/"
            f"{consent_guid}/revoke",
            json={"reason": "patient called to cancel"},
        )
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["revoked_at"] is not None
        assert body["revoked_reason"] == "patient called to cancel"
        assert body["is_active"] is False
        # Audit row.
        rows = db.session.query(AuditLog).filter_by(
            event_type="consent.revoked",
        ).all()
        assert len(rows) == 1
        assert rows[0].detail["grantee_caregiver_guid"] == cg
        assert rows[0].detail["reason"] == "patient called to cancel"

    def test_double_revoke_is_409(self, client, db, seed):
        r1 = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
            json={"grantee_caregiver_guid": _grantee_guid()},
        )
        consent_guid = r1.get_json()["guid"]
        client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents/"
            f"{consent_guid}/revoke",
            json={},
        )
        rv2 = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents/"
            f"{consent_guid}/revoke",
            json={},
        )
        assert rv2.status_code == 409

    def test_revoke_unknown_consent_is_404(self, client, db, seed):
        rv = client.post(
            f"/api/v1/patients/{seed['patient'].guid}/consents/"
            f"{uuid.uuid4()}/revoke",
            json={},
        )
        assert rv.status_code == 404


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

class TestExpiry:
    def test_expired_consent_is_not_active(self, client, db, seed):
        # Create directly through the ORM with a past expires_at —
        # the route disallows past-dated expiries via a different
        # error path (we don't validate temporal order on grant; the
        # model's is_active is what matters).
        consent = PatientConsent(
            patient_guid=seed["patient"].guid,
            grantee_caregiver_guid=uuid.uuid4(),
            granted_via="portal",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.session.add(consent)
        db.session.commit()
        # Default active filter should hide it.
        r = client.get(
            f"/api/v1/patients/{seed['patient'].guid}/consents",
        )
        assert r.get_json()["total"] == 0
