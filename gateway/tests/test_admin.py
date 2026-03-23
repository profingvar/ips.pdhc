"""Tests for admin UI routes — Steps 8.a through 8.e."""

import uuid

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.audit_log import AuditLog


def _seed_patient(db, family="Test", given="Patient"):
    """Create a patient and return the PatientIndex."""
    resource_id = str(uuid.uuid4())
    res = FhirResource(
        resource_type="Patient",
        resource_id=resource_id,
        resource_json={"resourceType": "Patient", "id": resource_id, "name": [{"family": family}]},
    )
    db.session.add(res)
    db.session.flush()

    pi = PatientIndex(
        fhir_resource_guid=res.guid,
        resource_id=resource_id,
        family_name=family,
        given_name=given,
    )
    db.session.add(pi)
    db.session.flush()
    return pi


def _seed_card_and_snapshot(db, patient):
    """Create an IPS card and snapshot for a patient."""
    card = IpsCard(
        patient_guid=patient.guid,
        title="Test Card",
        mode="full",
    )
    db.session.add(card)
    db.session.flush()

    from datetime import datetime, timezone
    snap = IpsSnapshot(
        card_guid=card.guid,
        bundle_json={"resourceType": "Bundle", "type": "document", "entry": []},
        composition_date=datetime.now(timezone.utc),
        mode="full",
        resource_count=2,
    )
    db.session.add(snap)
    db.session.flush()
    return card, snap


def _seed_destination_and_job(db, snapshot):
    """Create a push destination and job."""
    dest = PushDestination(
        name="Test Destination",
        destination_type="fhir_endpoint",
        endpoint_url="https://fhir.example.com/Bundle",
    )
    db.session.add(dest)
    db.session.flush()

    job = PushJob(
        snapshot_guid=snapshot.guid,
        destination_guid=dest.guid,
        status="queued",
    )
    db.session.add(job)
    db.session.flush()
    return dest, job


class TestDashboard:
    def test_dashboard_returns_html(self, client, db):
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"IPS Server Dashboard" in resp.data

    def test_dashboard_includes_css(self, client, db):
        resp = client.get("/admin/")
        assert b"pdhc.css" in resp.data

    def test_dashboard_shows_counts(self, client, db):
        _seed_patient(db)
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Patients" in resp.data

    def test_dashboard_shows_audit_events(self, client, db):
        event = AuditLog(
            event_type="test_event",
            actor_label="tester",
            request_method="GET",
            request_path="/test",
        )
        db.session.add(event)
        db.session.flush()

        resp = client.get("/admin/")
        assert b"test_event" in resp.data


class TestPatientBrowser:
    def test_patients_page_empty(self, client, db):
        resp = client.get("/admin/patients")
        assert resp.status_code == 200
        assert b"Patient Browser" in resp.data

    def test_patients_lists_patients(self, client, db):
        _seed_patient(db, family="Andersson", given="Erik")
        resp = client.get("/admin/patients")
        assert resp.status_code == 200
        assert b"Andersson" in resp.data
        assert b"Erik" in resp.data

    def test_patients_search(self, client, db):
        _seed_patient(db, family="Svensson", given="Anna")
        _seed_patient(db, family="Karlsson", given="Bo")

        resp = client.get("/admin/patients?q=Svensson")
        assert resp.status_code == 200
        assert b"Svensson" in resp.data
        assert b"Karlsson" not in resp.data

    def test_patients_search_no_results(self, client, db):
        _seed_patient(db, family="Svensson", given="Anna")
        resp = client.get("/admin/patients?q=Nonexistent")
        assert resp.status_code == 200
        assert b"No patients match" in resp.data

    def test_patient_detail(self, client, db):
        pi = _seed_patient(db, family="Johansson", given="Karin")
        resp = client.get(f"/admin/patients/{pi.guid}")
        assert resp.status_code == 200
        assert b"Johansson" in resp.data
        assert b"Karin" in resp.data
        assert str(pi.resource_id).encode() in resp.data

    def test_patient_detail_404(self, client, db):
        resp = client.get(f"/admin/patients/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_patient_detail_shows_resources(self, client, db):
        pi = _seed_patient(db)
        # Add a clinical resource for this patient
        cond = FhirResource(
            resource_type="Condition",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Condition"},
            patient_guid=pi.guid,
        )
        db.session.add(cond)
        db.session.flush()

        resp = client.get(f"/admin/patients/{pi.guid}")
        assert resp.status_code == 200
        assert b"Condition" in resp.data

    def test_patient_detail_shows_cards_and_snapshots(self, client, db):
        pi = _seed_patient(db)
        _seed_card_and_snapshot(db, pi)

        resp = client.get(f"/admin/patients/{pi.guid}")
        assert resp.status_code == 200
        assert b"Test Card" in resp.data
        assert b"Snapshot" in resp.data


class TestPushMonitor:
    def test_push_monitor_empty(self, client, db):
        resp = client.get("/admin/push")
        assert resp.status_code == 200
        assert b"Push Monitor" in resp.data

    def test_push_monitor_shows_destinations(self, client, db):
        dest = PushDestination(
            name="FHIR Endpoint A",
            destination_type="fhir_endpoint",
            endpoint_url="https://fhir.example.com",
        )
        db.session.add(dest)
        db.session.flush()

        resp = client.get("/admin/push")
        assert resp.status_code == 200
        assert b"FHIR Endpoint A" in resp.data

    def test_push_monitor_shows_jobs(self, client, db):
        pi = _seed_patient(db)
        card, snap = _seed_card_and_snapshot(db, pi)
        dest, job = _seed_destination_and_job(db, snap)

        resp = client.get("/admin/push")
        assert resp.status_code == 200
        assert b"Test Destination" in resp.data
        assert b"queued" in resp.data

    def test_push_monitor_filter_by_status(self, client, db):
        pi = _seed_patient(db)
        card, snap = _seed_card_and_snapshot(db, pi)
        dest, job = _seed_destination_and_job(db, snap)

        # Filter for completed — should not include our queued job
        resp = client.get("/admin/push?status=completed")
        assert resp.status_code == 200
        assert b"No push jobs" in resp.data

    def test_push_monitor_stats(self, client, db):
        pi = _seed_patient(db)
        card, snap = _seed_card_and_snapshot(db, pi)
        dest, job = _seed_destination_and_job(db, snap)

        resp = client.get("/admin/push")
        assert resp.status_code == 200
        assert b"Queued" in resp.data
        assert b"Completed" in resp.data
        assert b"Failed" in resp.data


class TestDocsIndex:
    def test_docs_index_page(self, client, db):
        resp = client.get("/admin/docs")
        assert resp.status_code == 200
        assert b"Documentation" in resp.data
        assert b"API Reference" in resp.data
        assert b"Capability Statement" in resp.data
        assert b"Operator Manual" in resp.data
        assert b"Technical Documentation" in resp.data

    def test_docs_index_has_download_links(self, client, db):
        resp = client.get("/admin/docs")
        assert resp.status_code == 200
        assert b"Download HTML" in resp.data


class TestDocsApi:
    def test_api_reference_page(self, client, db):
        resp = client.get("/admin/docs/api")
        assert resp.status_code == 200
        assert b"API Reference" in resp.data
        assert b"/fhir/Patient" in resp.data
        assert b"/api/v1/ips/cards" in resp.data
        assert b"/api/v1/push" in resp.data
        assert b"/api/v1/auth/keys" in resp.data

    def test_api_reference_download(self, client, db):
        resp = client.get("/admin/docs/api/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert b"API Reference" in resp.data


class TestDocsCapability:
    def test_capability_page(self, client, db):
        resp = client.get("/admin/docs/capability")
        assert resp.status_code == 200
        assert b"Capability Statement" in resp.data
        assert b"5.0.0" in resp.data
        assert b"Patient" in resp.data

    def test_capability_shows_resources(self, client, db):
        resp = client.get("/admin/docs/capability")
        assert resp.status_code == 200
        assert b"Condition" in resp.data
        assert b"Observation" in resp.data
        assert b"$ips" in resp.data

    def test_capability_download(self, client, db):
        resp = client.get("/admin/docs/capability/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert b"CapabilityStatement" in resp.data


class TestDocsManual:
    def test_manual_page(self, client, db):
        resp = client.get("/admin/docs/manual")
        assert resp.status_code == 200
        assert b"Operator Manual" in resp.data
        assert b"IPS Workflow" in resp.data
        assert b"API Key Management" in resp.data

    def test_manual_download(self, client, db):
        resp = client.get("/admin/docs/manual/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")


class TestDocsTechnical:
    def test_technical_page(self, client, db):
        resp = client.get("/admin/docs/technical")
        assert resp.status_code == 200
        assert b"Technical Documentation" in resp.data
        assert b"Architecture" in resp.data
        assert b"Security Model" in resp.data
        assert b"Data Model" in resp.data

    def test_technical_download(self, client, db):
        resp = client.get("/admin/docs/technical/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
