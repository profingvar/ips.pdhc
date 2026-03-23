"""Tests for application API endpoints — Steps 5.b through 5.i."""

import uuid

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex


def _seed_patient(db):
    """Create a patient in the database and return the PatientIndex."""
    resource_id = str(uuid.uuid4())
    res = FhirResource(
        resource_type="Patient",
        resource_id=resource_id,
        resource_json={"resourceType": "Patient", "id": resource_id, "name": [{"family": "Test"}]},
    )
    db.session.add(res)
    db.session.flush()

    pi = PatientIndex(
        fhir_resource_guid=res.guid,
        resource_id=resource_id,
        family_name="Test",
        given_name="Patient",
    )
    db.session.add(pi)
    db.session.flush()
    return pi


class TestIpsCardApi:
    def test_create_card(self, client, db):
        pi = _seed_patient(db)
        resp = client.post("/api/v1/ips/cards", json={
            "patient_guid": str(pi.guid),
            "title": "Test Card",
            "mode": "full",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Test Card"
        assert data["mode"] == "full"
        assert data["status"] == "active"

    def test_create_card_missing_patient(self, client, db):
        resp = client.post("/api/v1/ips/cards", json={
            "patient_guid": str(uuid.uuid4()),
        })
        assert resp.status_code == 404

    def test_list_cards(self, client, db):
        pi = _seed_patient(db)
        client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        resp = client.get("/api/v1/ips/cards")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_get_card(self, client, db):
        pi = _seed_patient(db)
        create_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = create_resp.get_json()["guid"]

        resp = client.get(f"/api/v1/ips/cards/{card_guid}")
        assert resp.status_code == 200
        assert resp.get_json()["guid"] == card_guid

    def test_update_card(self, client, db):
        pi = _seed_patient(db)
        create_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = create_resp.get_json()["guid"]

        resp = client.patch(f"/api/v1/ips/cards/{card_guid}", json={"mode": "minimal"})
        assert resp.status_code == 200
        assert resp.get_json()["mode"] == "minimal"

    def test_archive_card(self, client, db):
        pi = _seed_patient(db)
        create_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = create_resp.get_json()["guid"]

        resp = client.delete(f"/api/v1/ips/cards/{card_guid}")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "archived"


class TestIpsSnapshotApi:
    def test_create_snapshot(self, client, db):
        pi = _seed_patient(db)
        create_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = create_resp.get_json()["guid"]

        resp = client.post(f"/api/v1/ips/cards/{card_guid}/snapshots")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["card_guid"] == card_guid
        assert data["mode"] == "full"

    def test_list_snapshots(self, client, db):
        pi = _seed_patient(db)
        create_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = create_resp.get_json()["guid"]
        client.post(f"/api/v1/ips/cards/{card_guid}/snapshots")

        resp = client.get(f"/api/v1/ips/cards/{card_guid}/snapshots")
        assert resp.status_code == 200
        assert len(resp.get_json()) >= 1

    def test_get_snapshot_bundle(self, client, db):
        pi = _seed_patient(db)
        create_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = create_resp.get_json()["guid"]
        snap_resp = client.post(f"/api/v1/ips/cards/{card_guid}/snapshots")
        snap_guid = snap_resp.get_json()["guid"]

        resp = client.get(f"/api/v1/ips/snapshots/{snap_guid}/bundle")
        assert resp.status_code == 200
        bundle = resp.get_json()
        assert bundle["resourceType"] == "Bundle"


class TestClinicApi:
    def test_create_clinic(self, client, db):
        resp = client.post("/api/v1/clinics", json={"name": "Test Clinic"})
        assert resp.status_code == 201
        assert resp.get_json()["name"] == "Test Clinic"

    def test_list_clinics(self, client, db):
        client.post("/api/v1/clinics", json={"name": "Listed Clinic"})
        resp = client.get("/api/v1/clinics")
        assert resp.status_code == 200
        assert len(resp.get_json()) >= 1

    def test_update_clinic(self, client, db):
        create_resp = client.post("/api/v1/clinics", json={"name": "Original"})
        guid = create_resp.get_json()["guid"]
        resp = client.patch(f"/api/v1/clinics/{guid}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Updated"


class TestAuthKeyApi:
    def test_create_and_list_keys(self, client, db):
        resp = client.post("/api/v1/auth/keys", json={"label": "Test Key"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert "key" in data  # Plaintext shown once
        assert data["label"] == "Test Key"

        list_resp = client.get("/api/v1/auth/keys")
        assert list_resp.status_code == 200
        keys = list_resp.get_json()
        assert len(keys) >= 1
        # Key hash should not be in the listing
        for k in keys:
            assert "key" not in k

    def test_revoke_key(self, client, db):
        create_resp = client.post("/api/v1/auth/keys", json={"label": "Revoke Me"})
        guid = create_resp.get_json()["guid"]

        resp = client.delete(f"/api/v1/auth/keys/{guid}")
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False
        assert resp.get_json()["revoked_at"] is not None

    def test_rotate_key(self, client, db):
        create_resp = client.post("/api/v1/auth/keys", json={"label": "Rotate Me"})
        old_guid = create_resp.get_json()["guid"]

        resp = client.post(f"/api/v1/auth/keys/{old_guid}/rotate")
        assert resp.status_code == 201
        data = resp.get_json()
        assert "key" in data  # New plaintext
        assert data["guid"] != old_guid  # Different key


class TestAuditApi:
    def test_query_audit(self, client, db):
        # Generate some audit events by creating a clinic
        client.post("/api/v1/clinics", json={"name": "Audit Test"})

        resp = client.get("/api/v1/audit")
        assert resp.status_code == 200
        events = resp.get_json()
        assert isinstance(events, list)

    def test_audit_filter_by_event_type(self, client, db):
        client.post("/api/v1/clinics", json={"name": "Filter Test"})
        resp = client.get("/api/v1/audit?event_type=clinic_create")
        assert resp.status_code == 200


class TestPushApi:
    def test_create_destination(self, client, db):
        resp = client.post("/api/v1/push/destinations", json={
            "name": "Test Dest",
            "destination_type": "fhir_endpoint",
            "endpoint_url": "https://fhir.example.com/Bundle",
        })
        assert resp.status_code == 201
        assert resp.get_json()["name"] == "Test Dest"

    def test_create_push_job(self, client, db):
        # Setup: patient + card + snapshot + destination
        pi = _seed_patient(db)
        card_resp = client.post("/api/v1/ips/cards", json={"patient_guid": str(pi.guid)})
        card_guid = card_resp.get_json()["guid"]
        snap_resp = client.post(f"/api/v1/ips/cards/{card_guid}/snapshots")
        snap_guid = snap_resp.get_json()["guid"]

        dest_resp = client.post("/api/v1/push/destinations", json={
            "name": "Job Dest",
            "destination_type": "webhook",
            "endpoint_url": "https://example.com/hook",
        })
        dest_guid = dest_resp.get_json()["guid"]

        resp = client.post("/api/v1/push/jobs", json={
            "snapshot_guid": snap_guid,
            "destination_guid": dest_guid,
        })
        assert resp.status_code == 201
        assert resp.get_json()["status"] == "queued"
