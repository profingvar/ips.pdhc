"""Comprehensive API endpoint test script (Rules 9, 20).

Tests all API endpoints against the capability statement.
Can run against SQLite (pytest) or a live server (set IPS_BASE_URL).

Usage:
    pytest tests/test_api_endpoints.py -v          # against SQLite
    IPS_BASE_URL=http://localhost:9040 pytest ...   # against live server
"""

import os
import uuid

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("IPS_BASE_URL", "")


def _url(path: str) -> str:
    """Prefix path with base URL when testing against a live server."""
    return f"{BASE_URL}{path}" if BASE_URL else path


# ===========================================================================
# 1. PUBLIC / OPERATIONAL ENDPOINTS
# ===========================================================================

class TestPublicEndpoints:
    """Endpoints that require no authentication."""

    def test_health(self, client):
        resp = client.get(_url("/api/v1/health"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["service"] == "ips-server"
        assert data["database"] in ("connected", "disconnected")
        assert "timestamp" in data
        assert "version" in data

    def test_metrics(self, client):
        resp = client.get(_url("/api/v1/metrics"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert "counts" in data
        assert "timestamp" in data


# ===========================================================================
# 2. FHIR CAPABILITY STATEMENT
# ===========================================================================

class TestFhirCapability:
    """GET /fhir/metadata — CapabilityStatement."""

    def test_returns_capability_statement(self, client):
        resp = client.get(_url("/fhir/metadata"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resourceType"] == "CapabilityStatement"
        assert data["fhirVersion"] == "5.0.0"
        assert data["kind"] == "instance"

    def test_declares_supported_resources(self, client):
        resp = client.get(_url("/fhir/metadata"))
        data = resp.get_json()
        rest = data["rest"][0]
        resource_types = [r["type"] for r in rest["resource"]]
        expected = [
            "Patient", "Condition", "Observation", "MedicationStatement",
            "AllergyIntolerance", "Immunization", "Procedure",
            "DocumentReference", "DiagnosticReport",
        ]
        for rt in expected:
            assert rt in resource_types, f"{rt} missing from CapabilityStatement"

    def test_patient_has_ips_operation(self, client):
        resp = client.get(_url("/fhir/metadata"))
        data = resp.get_json()
        patient_entry = next(
            r for r in data["rest"][0]["resource"] if r["type"] == "Patient"
        )
        ops = [o["name"] for o in patient_entry.get("operation", [])]
        assert "ips" in ops

    def test_patient_search_params(self, client):
        resp = client.get(_url("/fhir/metadata"))
        data = resp.get_json()
        patient_entry = next(
            r for r in data["rest"][0]["resource"] if r["type"] == "Patient"
        )
        param_names = [p["name"] for p in patient_entry.get("searchParam", [])]
        for expected in ["identifier", "family", "given", "birthdate"]:
            assert expected in param_names, f"Patient searchParam '{expected}' missing"


# ===========================================================================
# 3. FHIR PATIENT CRUD
# ===========================================================================

class TestFhirPatientCrud:
    """POST/GET/PUT/search on /fhir/Patient."""

    def test_create_patient(self, client):
        resp = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "Eriksson", "given": ["Lars"]}],
            "gender": "male",
            "birthDate": "1970-06-15",
            "identifier": [{"system": "urn:oid:1.2.752.129.2.1.3.1", "value": "197006151234"}],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["resourceType"] == "Patient"
        assert data["name"][0]["family"] == "Eriksson"
        assert "id" in data

    def test_create_patient_rejects_wrong_type(self, client):
        resp = client.post(_url("/fhir/Patient"), json={"resourceType": "Observation"})
        assert resp.status_code == 400
        assert resp.get_json()["resourceType"] == "OperationOutcome"

    def test_read_patient(self, client):
        cr = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "Readtest"}],
        })
        pid = cr.get_json()["id"]
        resp = client.get(_url(f"/fhir/Patient/{pid}"))
        assert resp.status_code == 200
        assert resp.get_json()["id"] == pid

    def test_read_nonexistent_patient_returns_404(self, client):
        resp = client.get(_url(f"/fhir/Patient/{uuid.uuid4()}"))
        assert resp.status_code == 404
        assert resp.get_json()["resourceType"] == "OperationOutcome"

    def test_update_patient(self, client):
        cr = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "BeforeUpdate"}],
        })
        pid = cr.get_json()["id"]
        resp = client.put(_url(f"/fhir/Patient/{pid}"), json={
            "resourceType": "Patient",
            "name": [{"family": "AfterUpdate"}],
        })
        assert resp.status_code == 200
        assert resp.get_json()["name"][0]["family"] == "AfterUpdate"

    def test_update_nonexistent_patient(self, client):
        resp = client.put(_url(f"/fhir/Patient/{uuid.uuid4()}"), json={
            "resourceType": "Patient",
            "name": [{"family": "Ghost"}],
        })
        assert resp.status_code == 404

    def test_search_by_family(self, client):
        client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "Sökfamilj", "given": ["Anna"]}],
        })
        resp = client.get(_url("/fhir/Patient?family=Sökfamilj"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resourceType"] == "Bundle"
        assert data["type"] == "searchset"
        assert data["total"] >= 1

    def test_search_by_identifier(self, client):
        client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "IdSearch"}],
            "identifier": [{"system": "test", "value": "ID-SEARCH-001"}],
        })
        resp = client.get(_url("/fhir/Patient?identifier=ID-SEARCH-001"))
        assert resp.status_code == 200
        assert resp.get_json()["total"] >= 1

    def test_search_empty_result(self, client):
        resp = client.get(_url("/fhir/Patient?family=NoSuchPerson99999"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 0
        assert data["entry"] == []


# ===========================================================================
# 4. FHIR CLINICAL RESOURCE CRUD
# ===========================================================================

class TestFhirClinicalCrud:
    """POST/GET/search on clinical resource types."""

    CLINICAL_TYPES = [
        ("Condition", "subject"),
        ("Observation", "subject"),
        ("MedicationStatement", "subject"),
        ("AllergyIntolerance", "patient"),
        ("Immunization", "patient"),
        ("Procedure", "subject"),
        ("DocumentReference", "subject"),
        ("DiagnosticReport", "subject"),
    ]

    def _make_patient(self, client) -> str:
        resp = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "ClinicalHost"}],
        })
        return resp.get_json()["id"]

    @pytest.mark.parametrize("rtype,ref_field", CLINICAL_TYPES)
    def test_create_clinical_resource(self, client, rtype, ref_field):
        pid = self._make_patient(client)
        resource = {
            "resourceType": rtype,
            ref_field: {"reference": f"Patient/{pid}"},
        }
        resp = client.post(_url(f"/fhir/{rtype}"), json=resource)
        assert resp.status_code == 201, f"Failed to create {rtype}: {resp.get_json()}"
        assert resp.get_json()["resourceType"] == rtype

    @pytest.mark.parametrize("rtype,ref_field", CLINICAL_TYPES)
    def test_read_clinical_resource(self, client, rtype, ref_field):
        pid = self._make_patient(client)
        cr = client.post(_url(f"/fhir/{rtype}"), json={
            "resourceType": rtype,
            ref_field: {"reference": f"Patient/{pid}"},
        })
        rid = cr.get_json()["id"]
        resp = client.get(_url(f"/fhir/{rtype}/{rid}"))
        assert resp.status_code == 200
        assert resp.get_json()["id"] == rid

    @pytest.mark.parametrize("rtype,ref_field", CLINICAL_TYPES)
    def test_search_clinical_by_patient(self, client, rtype, ref_field):
        pid = self._make_patient(client)
        client.post(_url(f"/fhir/{rtype}"), json={
            "resourceType": rtype,
            ref_field: {"reference": f"Patient/{pid}"},
        })
        resp = client.get(_url(f"/fhir/{rtype}?patient={pid}"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["type"] == "searchset"
        assert data["total"] >= 1

    def test_unsupported_resource_type_rejected(self, client):
        resp = client.post(_url("/fhir/Banana"), json={"resourceType": "Banana"})
        assert resp.status_code == 400

    def test_wrong_resource_type_rejected(self, client):
        resp = client.post(_url("/fhir/Condition"), json={"resourceType": "Observation"})
        assert resp.status_code == 400


# ===========================================================================
# 5. FHIR $IPS OPERATION
# ===========================================================================

class TestFhirIpsOperation:
    """GET /fhir/Patient/<id>/$ips."""

    def _make_patient_with_data(self, client) -> str:
        resp = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "IpsPatient", "given": ["Test"]}],
            "birthDate": "1990-01-01",
            "gender": "female",
        })
        pid = resp.get_json()["id"]

        # Add clinical data
        client.post(_url("/fhir/Condition"), json={
            "resourceType": "Condition",
            "subject": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "73211009", "display": "Diabetes mellitus"}]},
        })
        client.post(_url("/fhir/MedicationStatement"), json={
            "resourceType": "MedicationStatement",
            "subject": {"reference": f"Patient/{pid}"},
            "status": "active",
        })
        client.post(_url("/fhir/AllergyIntolerance"), json={
            "resourceType": "AllergyIntolerance",
            "patient": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "91936005", "display": "Penicillin allergy"}]},
        })
        client.post(_url("/fhir/Immunization"), json={
            "resourceType": "Immunization",
            "patient": {"reference": f"Patient/{pid}"},
            "status": "completed",
        })
        return pid

    def test_ips_full_mode(self, client):
        pid = self._make_patient_with_data(client)
        resp = client.get(_url(f"/fhir/Patient/{pid}/$ips"))
        assert resp.status_code == 200
        bundle = resp.get_json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "document"
        assert "meta" in bundle
        assert any("ips" in p for p in bundle["meta"].get("profile", []))
        # Must have Composition as first entry
        assert bundle["entry"][0]["resource"]["resourceType"] == "Composition"
        # Must have Patient
        resource_types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "Patient" in resource_types
        assert "Composition" in resource_types

    def test_ips_minimal_mode(self, client):
        pid = self._make_patient_with_data(client)
        resp = client.get(_url(f"/fhir/Patient/{pid}/$ips?mode=minimal"))
        assert resp.status_code == 200
        bundle = resp.get_json()
        assert bundle["resourceType"] == "Bundle"
        # Minimal should NOT include Immunization
        composition = bundle["entry"][0]["resource"]
        section_titles = [s["title"] for s in composition.get("section", [])]
        assert "Active Problems" in section_titles
        assert "Medication Summary" in section_titles
        assert "Allergies and Intolerances" in section_titles
        assert "Immunizations" not in section_titles

    def test_ips_composition_has_sections(self, client):
        pid = self._make_patient_with_data(client)
        resp = client.get(_url(f"/fhir/Patient/{pid}/$ips"))
        bundle = resp.get_json()
        composition = bundle["entry"][0]["resource"]
        assert composition["resourceType"] == "Composition"
        assert composition["status"] == "final"
        assert composition["type"]["coding"][0]["code"] == "60591-5"
        assert len(composition["section"]) > 0

    def test_ips_empty_sections_have_reason(self, client):
        # Patient with no clinical data
        resp = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "Empty"}],
        })
        pid = resp.get_json()["id"]
        resp = client.get(_url(f"/fhir/Patient/{pid}/$ips"))
        bundle = resp.get_json()
        composition = bundle["entry"][0]["resource"]
        for section in composition.get("section", []):
            if "entry" not in section:
                assert "emptyReason" in section
                assert section["emptyReason"]["coding"][0]["code"] == "unavailable"

    def test_ips_nonexistent_patient_returns_404(self, client):
        resp = client.get(_url(f"/fhir/Patient/{uuid.uuid4()}/$ips"))
        assert resp.status_code == 404

    def test_ips_bundle_timestamp(self, client):
        pid = self._make_patient_with_data(client)
        resp = client.get(_url(f"/fhir/Patient/{pid}/$ips"))
        bundle = resp.get_json()
        assert "timestamp" in bundle


# ===========================================================================
# 6. APPLICATION API — IPS CARDS
# ===========================================================================

class TestAppIpsCards:
    """CRUD on /api/v1/ips/cards."""

    def _make_patient_index(self, client, db=None):
        """Create a patient via FHIR API and return its PatientIndex guid."""
        resp = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "CardPatient"}],
        })
        pid = resp.get_json()["id"]
        # Look up patient_index guid via search
        search = client.get(_url(f"/fhir/Patient?family=CardPatient"))
        # We need the guid — get it from metrics or internal. For testing
        # we use the patient endpoint's internal data.
        from app.models.patient_index import PatientIndex
        from app.models.base import db as _db
        pi = _db.session.query(PatientIndex).filter_by(resource_id=pid).first()
        return str(pi.guid) if pi else None

    def test_create_card(self, client, db):
        pguid = self._make_patient_index(client)
        resp = client.post(_url("/api/v1/ips/cards"), json={
            "patient_guid": pguid,
            "title": "My IPS Card",
            "mode": "full",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "active"
        assert data["mode"] == "full"
        assert data["title"] == "My IPS Card"
        assert "guid" in data

    def test_create_card_missing_patient_guid(self, client, db):
        resp = client.post(_url("/api/v1/ips/cards"), json={})
        assert resp.status_code == 400

    def test_create_card_nonexistent_patient(self, client, db):
        resp = client.post(_url("/api/v1/ips/cards"), json={
            "patient_guid": str(uuid.uuid4()),
        })
        assert resp.status_code == 404

    def test_list_cards(self, client, db):
        pguid = self._make_patient_index(client)
        client.post(_url("/api/v1/ips/cards"), json={"patient_guid": pguid})
        resp = client.get(_url("/api/v1/ips/cards"))
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)
        assert len(resp.get_json()) >= 1

    def test_list_cards_filter_by_patient(self, client, db):
        pguid = self._make_patient_index(client)
        client.post(_url("/api/v1/ips/cards"), json={"patient_guid": pguid})
        resp = client.get(_url(f"/api/v1/ips/cards?patient_guid={pguid}"))
        assert resp.status_code == 200
        for card in resp.get_json():
            assert card["patient_guid"] == pguid

    def test_get_card(self, client, db):
        pguid = self._make_patient_index(client)
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": pguid})
        card_guid = cr.get_json()["guid"]
        resp = client.get(_url(f"/api/v1/ips/cards/{card_guid}"))
        assert resp.status_code == 200
        assert resp.get_json()["guid"] == card_guid

    def test_get_nonexistent_card(self, client, db):
        resp = client.get(_url(f"/api/v1/ips/cards/{uuid.uuid4()}"))
        assert resp.status_code == 404

    def test_update_card_mode(self, client, db):
        pguid = self._make_patient_index(client)
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": pguid, "mode": "full"})
        card_guid = cr.get_json()["guid"]
        resp = client.patch(_url(f"/api/v1/ips/cards/{card_guid}"), json={"mode": "minimal"})
        assert resp.status_code == 200
        assert resp.get_json()["mode"] == "minimal"

    def test_update_card_title(self, client, db):
        pguid = self._make_patient_index(client)
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": pguid})
        card_guid = cr.get_json()["guid"]
        resp = client.patch(_url(f"/api/v1/ips/cards/{card_guid}"), json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "New Title"

    def test_archive_card(self, client, db):
        pguid = self._make_patient_index(client)
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": pguid})
        card_guid = cr.get_json()["guid"]
        resp = client.delete(_url(f"/api/v1/ips/cards/{card_guid}"))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "archived"


# ===========================================================================
# 7. APPLICATION API — IPS SNAPSHOTS
# ===========================================================================

class TestAppIpsSnapshots:
    """Snapshot lifecycle on /api/v1/ips/..."""

    def _make_card(self, client):
        pr = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": "SnapPatient"}],
        })
        pid = pr.get_json()["id"]
        from app.models.patient_index import PatientIndex
        from app.models.base import db
        pi = db.session.query(PatientIndex).filter_by(resource_id=pid).first()
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": str(pi.guid)})
        return cr.get_json()["guid"]

    def test_create_snapshot(self, client, db):
        card_guid = self._make_card(client)
        resp = client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["card_guid"] == card_guid
        assert data["mode"] == "full"
        assert "resource_count" in data
        assert "composition_date" in data

    def test_list_snapshots(self, client, db):
        card_guid = self._make_card(client)
        client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        resp = client.get(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        assert resp.status_code == 200
        assert len(resp.get_json()) >= 2

    def test_get_snapshot_metadata(self, client, db):
        card_guid = self._make_card(client)
        sr = client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        snap_guid = sr.get_json()["guid"]
        resp = client.get(_url(f"/api/v1/ips/snapshots/{snap_guid}"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["guid"] == snap_guid
        assert "bundle_json" not in data  # Metadata only

    def test_get_snapshot_bundle(self, client, db):
        card_guid = self._make_card(client)
        sr = client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        snap_guid = sr.get_json()["guid"]
        resp = client.get(_url(f"/api/v1/ips/snapshots/{snap_guid}/bundle"))
        assert resp.status_code == 200
        bundle = resp.get_json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "document"

    def test_get_nonexistent_snapshot(self, client, db):
        resp = client.get(_url(f"/api/v1/ips/snapshots/{uuid.uuid4()}"))
        assert resp.status_code == 404


# ===========================================================================
# 8. APPLICATION API — PUSH DESTINATIONS
# ===========================================================================

class TestAppPushDestinations:
    """CRUD on /api/v1/push/destinations."""

    def test_create_destination(self, client, db):
        resp = client.post(_url("/api/v1/push/destinations"), json={
            "name": "External FHIR Server",
            "destination_type": "fhir_endpoint",
            "endpoint_url": "https://fhir.external.org/Bundle",
            "auth_method": "bearer",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "External FHIR Server"
        assert data["is_active"] is True

    def test_create_destination_missing_fields(self, client, db):
        resp = client.post(_url("/api/v1/push/destinations"), json={"name": "Incomplete"})
        assert resp.status_code == 400

    def test_list_destinations(self, client, db):
        client.post(_url("/api/v1/push/destinations"), json={
            "name": "Listed", "destination_type": "webhook", "endpoint_url": "https://hook.test",
        })
        resp = client.get(_url("/api/v1/push/destinations"))
        assert resp.status_code == 200
        assert len(resp.get_json()) >= 1

    def test_get_destination(self, client, db):
        cr = client.post(_url("/api/v1/push/destinations"), json={
            "name": "GetMe", "destination_type": "webhook", "endpoint_url": "https://hook.test",
        })
        guid = cr.get_json()["guid"]
        resp = client.get(_url(f"/api/v1/push/destinations/{guid}"))
        assert resp.status_code == 200
        assert resp.get_json()["guid"] == guid

    def test_update_destination(self, client, db):
        cr = client.post(_url("/api/v1/push/destinations"), json={
            "name": "UpdateMe", "destination_type": "webhook", "endpoint_url": "https://old.test",
        })
        guid = cr.get_json()["guid"]
        resp = client.patch(_url(f"/api/v1/push/destinations/{guid}"), json={
            "endpoint_url": "https://new.test",
        })
        assert resp.status_code == 200
        assert resp.get_json()["endpoint_url"] == "https://new.test"

    def test_deactivate_destination(self, client, db):
        cr = client.post(_url("/api/v1/push/destinations"), json={
            "name": "DeactivateMe", "destination_type": "webhook", "endpoint_url": "https://bye.test",
        })
        guid = cr.get_json()["guid"]
        resp = client.delete(_url(f"/api/v1/push/destinations/{guid}"))
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False


# ===========================================================================
# 9. APPLICATION API — PUSH JOBS
# ===========================================================================

class TestAppPushJobs:
    """CRUD on /api/v1/push/jobs."""

    def _setup(self, client):
        """Create patient → card → snapshot → destination, return (snap_guid, dest_guid)."""
        pr = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient", "name": [{"family": "PushJobPt"}],
        })
        pid = pr.get_json()["id"]
        from app.models.patient_index import PatientIndex
        from app.models.base import db
        pi = db.session.query(PatientIndex).filter_by(resource_id=pid).first()
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": str(pi.guid)})
        card_guid = cr.get_json()["guid"]
        sr = client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        snap_guid = sr.get_json()["guid"]
        dr = client.post(_url("/api/v1/push/destinations"), json={
            "name": "JobDest", "destination_type": "webhook", "endpoint_url": "https://job.test",
        })
        dest_guid = dr.get_json()["guid"]
        return snap_guid, dest_guid

    def test_create_push_job(self, client, db):
        snap_guid, dest_guid = self._setup(client)
        resp = client.post(_url("/api/v1/push/jobs"), json={
            "snapshot_guid": snap_guid,
            "destination_guid": dest_guid,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "queued"
        assert data["attempts"] == 0

    def test_create_job_missing_fields(self, client, db):
        resp = client.post(_url("/api/v1/push/jobs"), json={})
        assert resp.status_code == 400

    def test_create_job_nonexistent_snapshot(self, client, db):
        _, dest_guid = self._setup(client)
        resp = client.post(_url("/api/v1/push/jobs"), json={
            "snapshot_guid": str(uuid.uuid4()),
            "destination_guid": dest_guid,
        })
        assert resp.status_code == 404

    def test_list_jobs(self, client, db):
        snap_guid, dest_guid = self._setup(client)
        client.post(_url("/api/v1/push/jobs"), json={
            "snapshot_guid": snap_guid, "destination_guid": dest_guid,
        })
        resp = client.get(_url("/api/v1/push/jobs"))
        assert resp.status_code == 200
        assert len(resp.get_json()) >= 1

    def test_list_jobs_filter_by_status(self, client, db):
        snap_guid, dest_guid = self._setup(client)
        client.post(_url("/api/v1/push/jobs"), json={
            "snapshot_guid": snap_guid, "destination_guid": dest_guid,
        })
        resp = client.get(_url("/api/v1/push/jobs?status=queued"))
        assert resp.status_code == 200
        for job in resp.get_json():
            assert job["status"] == "queued"

    def test_get_job(self, client, db):
        snap_guid, dest_guid = self._setup(client)
        cr = client.post(_url("/api/v1/push/jobs"), json={
            "snapshot_guid": snap_guid, "destination_guid": dest_guid,
        })
        job_guid = cr.get_json()["guid"]
        resp = client.get(_url(f"/api/v1/push/jobs/{job_guid}"))
        assert resp.status_code == 200
        assert resp.get_json()["guid"] == job_guid


# ===========================================================================
# 10. APPLICATION API — API KEY MANAGEMENT
# ===========================================================================

class TestAppApiKeys:
    """CRUD on /api/v1/auth/keys."""

    def test_create_key_returns_plaintext_once(self, client, db):
        resp = client.post(_url("/api/v1/auth/keys"), json={
            "label": "Integration Key",
            "scopes": ["read:fhir", "write:fhir"],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "key" in data  # Plaintext shown once
        assert len(data["key"]) > 30
        assert data["label"] == "Integration Key"
        assert data["prefix"] == data["key"][:8]
        assert data["is_active"] is True

    def test_list_keys_hides_plaintext(self, client, db):
        client.post(_url("/api/v1/auth/keys"), json={"label": "Hidden"})
        resp = client.get(_url("/api/v1/auth/keys"))
        assert resp.status_code == 200
        for key in resp.get_json():
            assert "key" not in key
            assert "key_hash" not in key

    def test_revoke_key(self, client, db):
        cr = client.post(_url("/api/v1/auth/keys"), json={"label": "ToRevoke"})
        guid = cr.get_json()["guid"]
        resp = client.delete(_url(f"/api/v1/auth/keys/{guid}"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_active"] is False
        assert data["revoked_at"] is not None

    def test_revoke_nonexistent_key(self, client, db):
        resp = client.delete(_url(f"/api/v1/auth/keys/{uuid.uuid4()}"))
        assert resp.status_code == 404

    def test_rotate_key(self, client, db):
        cr = client.post(_url("/api/v1/auth/keys"), json={"label": "ToRotate"})
        old_guid = cr.get_json()["guid"]
        old_key = cr.get_json()["key"]

        resp = client.post(_url(f"/api/v1/auth/keys/{old_guid}/rotate"))
        assert resp.status_code == 201
        data = resp.get_json()
        assert "key" in data
        assert data["key"] != old_key
        assert data["guid"] != old_guid
        assert data["label"] == "ToRotate"

    def test_rotate_nonexistent_key(self, client, db):
        resp = client.post(_url(f"/api/v1/auth/keys/{uuid.uuid4()}/rotate"))
        assert resp.status_code == 404


# ===========================================================================
# 11. APPLICATION API — AUDIT LOG
# ===========================================================================

class TestAppAuditLog:
    """Query on /api/v1/audit."""

    def test_query_all_events(self, client, db):
        # Generate an audit event
        client.post(_url("/api/v1/clinics"), json={"name": "AuditClinic"})
        resp = client.get(_url("/api/v1/audit"))
        assert resp.status_code == 200
        events = resp.get_json()
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_filter_by_event_type(self, client, db):
        client.post(_url("/api/v1/clinics"), json={"name": "AuditFilter"})
        resp = client.get(_url("/api/v1/audit?event_type=clinic_create"))
        assert resp.status_code == 200
        for event in resp.get_json():
            assert event["event_type"] == "clinic_create"

    def test_limit_results(self, client, db):
        for i in range(5):
            client.post(_url("/api/v1/clinics"), json={"name": f"LimitClinic{i}"})
        resp = client.get(_url("/api/v1/audit?limit=3"))
        assert resp.status_code == 200
        assert len(resp.get_json()) <= 3

    def test_audit_records_bundle_read(self, client, db):
        # Create patient → card → snapshot → read bundle
        pr = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient", "name": [{"family": "AuditBundlePt"}],
        })
        pid = pr.get_json()["id"]
        from app.models.patient_index import PatientIndex
        from app.models.base import db as _db
        pi = _db.session.query(PatientIndex).filter_by(resource_id=pid).first()
        cr = client.post(_url("/api/v1/ips/cards"), json={"patient_guid": str(pi.guid)})
        card_guid = cr.get_json()["guid"]
        sr = client.post(_url(f"/api/v1/ips/cards/{card_guid}/snapshots"))
        snap_guid = sr.get_json()["guid"]
        client.get(_url(f"/api/v1/ips/snapshots/{snap_guid}/bundle"))

        resp = client.get(_url("/api/v1/audit?event_type=ips_bundle_read"))
        assert resp.status_code == 200
        events = resp.get_json()
        assert any(str(snap_guid) in str(e.get("resource_guid", "")) for e in events)


# ===========================================================================
# 12. APPLICATION API — CLINICS
# ===========================================================================

class TestAppClinics:
    """CRUD on /api/v1/clinics."""

    def test_create_clinic(self, client, db):
        resp = client.post(_url("/api/v1/clinics"), json={
            "name": "Stockholm Clinic",
            "identifier": "SE-CLINIC-001",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Stockholm Clinic"
        assert data["identifier"] == "SE-CLINIC-001"
        assert data["is_active"] is True

    def test_create_clinic_missing_name(self, client, db):
        resp = client.post(_url("/api/v1/clinics"), json={})
        assert resp.status_code == 400

    def test_list_clinics(self, client, db):
        client.post(_url("/api/v1/clinics"), json={"name": "Listed Clinic"})
        resp = client.get(_url("/api/v1/clinics"))
        assert resp.status_code == 200
        assert len(resp.get_json()) >= 1

    def test_get_clinic(self, client, db):
        cr = client.post(_url("/api/v1/clinics"), json={"name": "Get Clinic"})
        guid = cr.get_json()["guid"]
        resp = client.get(_url(f"/api/v1/clinics/{guid}"))
        assert resp.status_code == 200
        assert resp.get_json()["guid"] == guid

    def test_get_nonexistent_clinic(self, client, db):
        resp = client.get(_url(f"/api/v1/clinics/{uuid.uuid4()}"))
        assert resp.status_code == 404

    def test_update_clinic(self, client, db):
        cr = client.post(_url("/api/v1/clinics"), json={"name": "Original"})
        guid = cr.get_json()["guid"]
        resp = client.patch(_url(f"/api/v1/clinics/{guid}"), json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Renamed"

    def test_deactivate_clinic(self, client, db):
        cr = client.post(_url("/api/v1/clinics"), json={"name": "Deactivate Me"})
        guid = cr.get_json()["guid"]
        resp = client.patch(_url(f"/api/v1/clinics/{guid}"), json={"is_active": False})
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False


class TestClinicPatients:
    """GET /api/v1/clinics/{guid}/patients — list patients assigned to a clinic."""

    @staticmethod
    def _create_patient(client, family, given, identifier):
        resp = client.post(_url("/fhir/Patient"), json={
            "resourceType": "Patient",
            "name": [{"family": family, "given": [given]}],
            "identifier": [{"system": "test", "value": identifier}],
        })
        assert resp.status_code == 201
        return resp.get_json()["id"]

    @staticmethod
    def _assign(db, patient_resource_id, clinic_guid):
        from app.models.patient_index import PatientIndex, PatientClinicAssignment
        pi = db.session.query(PatientIndex).filter_by(resource_id=patient_resource_id).first()
        assert pi is not None, "PatientIndex was not synced from POST /fhir/Patient"
        db.session.add(PatientClinicAssignment(
            patient_guid=pi.guid, clinic_guid=clinic_guid,
        ))
        db.session.commit()
        return pi.guid

    def test_lists_patients_for_clinic(self, client, db):
        clinic = client.post(_url("/api/v1/clinics"), json={"name": "Stockholm"}).get_json()
        rid_a = self._create_patient(client, "Andersson", "Anna", "A-1")
        rid_b = self._create_patient(client, "Bergström", "Björn", "B-1")
        self._assign(db, rid_a, clinic["guid"])
        self._assign(db, rid_b, clinic["guid"])

        resp = client.get(_url(f"/api/v1/clinics/{clinic['guid']}/patients"))
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        # Ordered by family_name asc
        assert data[0]["family_name"] == "Andersson"
        assert data[1]["family_name"] == "Bergström"
        # Shape matches PatientIndex.to_dict()
        assert {"guid", "resource_id", "family_name", "given_name", "birth_date"}.issubset(data[0].keys())

    def test_does_not_leak_patients_from_other_clinics(self, client, db):
        a = client.post(_url("/api/v1/clinics"), json={"name": "ClinicA"}).get_json()
        b = client.post(_url("/api/v1/clinics"), json={"name": "ClinicB"}).get_json()
        rid_a = self._create_patient(client, "OnlyInA", "Alice", "ID-A")
        rid_b = self._create_patient(client, "OnlyInB", "Bob", "ID-B")
        self._assign(db, rid_a, a["guid"])
        self._assign(db, rid_b, b["guid"])

        resp = client.get(_url(f"/api/v1/clinics/{a['guid']}/patients"))
        assert resp.status_code == 200
        names = [p["family_name"] for p in resp.get_json()]
        assert names == ["OnlyInA"]

    def test_patient_in_two_clinics_appears_in_both(self, client, db):
        a = client.post(_url("/api/v1/clinics"), json={"name": "ClinicA"}).get_json()
        b = client.post(_url("/api/v1/clinics"), json={"name": "ClinicB"}).get_json()
        rid = self._create_patient(client, "Dual", "Diana", "ID-DUAL")
        self._assign(db, rid, a["guid"])
        self._assign(db, rid, b["guid"])

        ra = client.get(_url(f"/api/v1/clinics/{a['guid']}/patients")).get_json()
        rb = client.get(_url(f"/api/v1/clinics/{b['guid']}/patients")).get_json()
        assert [p["family_name"] for p in ra] == ["Dual"]
        assert [p["family_name"] for p in rb] == ["Dual"]

    def test_unknown_clinic_returns_404(self, client, db):
        resp = client.get(_url(f"/api/v1/clinics/{uuid.uuid4()}/patients"))
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Clinic not found"

    def test_clinic_with_no_patients_returns_empty(self, client, db):
        clinic = client.post(_url("/api/v1/clinics"), json={"name": "Empty"}).get_json()
        resp = client.get(_url(f"/api/v1/clinics/{clinic['guid']}/patients"))
        assert resp.status_code == 200
        assert resp.get_json() == []


# ===========================================================================
# 13. ADMIN UI
# ===========================================================================

class TestAdminUi:
    """GET /admin/ — dashboard page."""

    def test_dashboard_returns_html(self, client, db):
        resp = client.get(_url("/admin/"))
        assert resp.status_code == 200
        assert b"IPS Server Dashboard" in resp.data
        assert b"pdhc.css" in resp.data
