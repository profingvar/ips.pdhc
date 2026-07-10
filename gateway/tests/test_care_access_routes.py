"""D3 (#406) — care-access-check + nödöppning endpoint tests."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    AuditLog,
    EmergencyAccess,
    FhirResource,
    PatientBlock,
    PatientConsent,
    PatientIndex,
)

UNIT_A1 = str(uuid.uuid4())
UNIT_B1 = str(uuid.uuid4())
ORG_A = str(uuid.uuid4())
ORG_B = str(uuid.uuid4())


@pytest.fixture
def patient(client, db):
    fhir = FhirResource(resource_type="Patient",
                        resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid,
                     resource_id=str(uuid.uuid4()),
                     family_name="Svensson", given_name="Sven")
    db.session.add(p)
    db.session.commit()
    return p


def _check(client, patient, reader_unit, reader_org):
    return client.post(
        f"/api/v1/patients/{patient.guid}/care-access-check",
        json={"reader_care_unit_guid": reader_unit,
              "reader_care_organisation_guid": reader_org,
              "author_clinic_guid": UNIT_A1,
              "author_caregiver_guid": ORG_A})


def test_check_zone3_denied_without_consent_and_audited(client, db, patient):
    r = _check(client, patient, UNIT_B1, ORG_B)
    assert r.status_code == 200
    body = r.get_json()
    assert body["allowed"] is False
    assert body["zone"] == 3
    assert body["reason"] == "no_sharing_consent"
    row = (db.session.query(AuditLog)
           .filter_by(event_type="care_access.check").first())
    assert row is not None
    assert row.detail["purpose"] == "care"
    assert row.detail["allowed"] is False


def test_check_zone3_allowed_with_consent(client, db, patient):
    db.session.add(PatientConsent(patient_guid=patient.guid,
                                  grantee_caregiver_guid=ORG_B,
                                  granted_via="portal"))
    db.session.commit()
    body = _check(client, patient, UNIT_B1, ORG_B).get_json()
    assert body["allowed"] is True
    assert body["access_basis"] == "cross_org_consent"


def test_check_yttre_sparr_beats_consent(client, db, patient):
    db.session.add(PatientConsent(patient_guid=patient.guid,
                                  grantee_caregiver_guid=ORG_B,
                                  granted_via="portal"))
    db.session.add(PatientBlock(patient_guid=patient.guid,
                                source_scope_type="caregiver",
                                source_scope_id=ORG_A))
    db.session.commit()
    body = _check(client, patient, UNIT_B1, ORG_B).get_json()
    assert body["allowed"] is False
    assert body["reason"] == "yttre_sparr"


def test_check_zone2_inre_sparr(client, db, patient):
    db.session.add(PatientBlock(patient_guid=patient.guid,
                                source_scope_type="clinic",
                                source_scope_id=UNIT_A1))
    db.session.commit()
    body = _check(client, patient, str(uuid.uuid4()), ORG_A).get_json()
    assert body["allowed"] is False
    assert body["zone"] == 2
    assert body["reason"] == "inre_sparr"


# --- nödöppning ---------------------------------------------------------

def _grant(client, patient, **over):
    body = {"reader_care_unit_guid": UNIT_B1,
            "reader_care_organisation_guid": ORG_B,
            "reason": "Medvetslös patient på akuten, misstänkt intox.",
            "attest": True}
    body.update(over)
    return client.post(
        f"/api/v1/patients/{patient.guid}/emergency-access", json=body)


def test_emergency_requires_reason_and_attestation(client, db, patient):
    assert _grant(client, patient, reason="").status_code == 400
    assert _grant(client, patient, attest=False).status_code == 400
    assert _grant(client, patient, attest="yes").status_code == 400


def test_emergency_role_gate(client, db, patient, monkeypatch):
    from app.models.user import User
    from app.services import auth_service
    monkeypatch.setattr(
        auth_service, "_synthetic_dev_user",
        lambda: User(username="dev-op", display_name="Op",
                     role="operator", is_active=True, is_superuser=False))
    assert _grant(client, patient).status_code == 403


def test_emergency_grant_created_audited_and_overrides(client, db, patient):
    # spärr + no consent — Zone 3 denies…
    db.session.add(PatientBlock(patient_guid=patient.guid,
                                source_scope_type="caregiver",
                                source_scope_id=ORG_A))
    db.session.commit()
    assert _check(client, patient, UNIT_B1, ORG_B).get_json()["allowed"] is False

    r = _grant(client, patient)
    assert r.status_code == 201
    grant = r.get_json()
    assert grant["is_active"] is True
    assert grant["reason"].startswith("Medvetslös")

    audit = (db.session.query(AuditLog)
             .filter_by(event_type="emergency_access.granted").one())
    assert audit.detail["access_basis"] == "emergency"
    assert audit.detail["attested"] is True

    # …and now the same read is allowed with access_basis=emergency.
    body = _check(client, patient, UNIT_B1, ORG_B).get_json()
    assert body["allowed"] is True
    assert body["access_basis"] == "emergency"
    assert body["emergency_access_guid"] == grant["guid"]


def test_emergency_grant_is_unit_scoped_and_expires(client, db, patient):
    r = _grant(client, patient, expires_in=60)
    assert r.status_code == 201
    # another reading unit gets no benefit
    other_unit = str(uuid.uuid4())
    body = _check(client, patient, other_unit, ORG_B).get_json()
    assert body["allowed"] is False
    # expiry bites
    g = db.session.query(EmergencyAccess).one()
    g.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session.commit()
    body = _check(client, patient, UNIT_B1, ORG_B).get_json()
    assert body["allowed"] is False


def test_emergency_expiry_bounds(client, db, patient):
    assert _grant(client, patient, expires_in=0).status_code == 400
    assert _grant(client, patient,
                  expires_in=8 * 24 * 3600).status_code == 400


def test_sso_bearer_resolves_local_user_by_email(client, db, patient,
                                                 monkeypatch):
    """The SSO blob has no `username` — the bearer lookup falls back to
    email (kontroller demo finding, 2026-07-10)."""
    from app.models.user import User
    from app.services import auth_service

    db.session.add(User(username="pro@example.se", display_name="Pro",
                        role="operator", is_active=True, is_superuser=False))
    db.session.commit()
    monkeypatch.setitem(client.application.config, "AUTH_DISABLED", False)
    monkeypatch.setattr(auth_service, "resolve_sso_user",
                        lambda tok: {"email": "pro@example.se",
                                     "user_type": "professional",
                                     "session_id": "sid-bearer-1"})
    r = client.post(
        f"/api/v1/patients/{patient.guid}/care-access-check",
        headers={"Authorization": "Bearer t"},
        json={"reader_care_unit_guid": UNIT_B1,
              "reader_care_organisation_guid": ORG_B,
              "author_clinic_guid": UNIT_A1,
              "author_caregiver_guid": ORG_A})
    assert r.status_code == 200
