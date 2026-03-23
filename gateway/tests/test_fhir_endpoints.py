"""Tests for FHIR REST endpoints — Steps 4.a through 4.f."""

import uuid


class TestCapabilityStatement:
    def test_metadata_returns_capability_statement(self, client):
        resp = client.get("/fhir/metadata")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resourceType"] == "CapabilityStatement"
        assert data["fhirVersion"] == "5.0.0"


class TestPatientCRUD:
    def test_create_patient(self, client):
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "Andersson", "given": ["Erik"]}],
            "gender": "male",
            "birthDate": "1985-03-15",
            "identifier": [{
                "system": "urn:oid:1.2.752.129.2.1.3.1",
                "value": "198503151234",
            }],
        }
        resp = client.post("/fhir/Patient", json=patient)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["resourceType"] == "Patient"
        assert "id" in data

    def test_read_patient(self, client):
        # Create first
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "Johansson", "given": ["Maria"]}],
        }
        create_resp = client.post("/fhir/Patient", json=patient)
        patient_id = create_resp.get_json()["id"]

        # Read
        resp = client.get(f"/fhir/Patient/{patient_id}")
        assert resp.status_code == 200
        assert resp.get_json()["id"] == patient_id

    def test_read_nonexistent_patient(self, client):
        resp = client.get(f"/fhir/Patient/{uuid.uuid4()}")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["resourceType"] == "OperationOutcome"

    def test_update_patient(self, client):
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "Before", "given": ["Update"]}],
        }
        create_resp = client.post("/fhir/Patient", json=patient)
        patient_id = create_resp.get_json()["id"]

        updated = {
            "resourceType": "Patient",
            "name": [{"family": "After", "given": ["Update"]}],
        }
        resp = client.put(f"/fhir/Patient/{patient_id}", json=updated)
        assert resp.status_code == 200
        assert resp.get_json()["name"][0]["family"] == "After"

    def test_search_patients(self, client):
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "Searchable", "given": ["Test"]}],
        }
        client.post("/fhir/Patient", json=patient)

        resp = client.get("/fhir/Patient?family=Searchable")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resourceType"] == "Bundle"
        assert data["type"] == "searchset"
        assert data["total"] >= 1

    def test_create_patient_wrong_resource_type(self, client):
        resp = client.post("/fhir/Patient", json={"resourceType": "Observation"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["resourceType"] == "OperationOutcome"


class TestClinicalResourceCRUD:
    def _create_patient(self, client):
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "Clinical", "given": ["Test"]}],
        }
        resp = client.post("/fhir/Patient", json=patient)
        return resp.get_json()["id"]

    def test_create_condition(self, client):
        patient_id = self._create_patient(client)
        condition = {
            "resourceType": "Condition",
            "subject": {"reference": f"Patient/{patient_id}"},
            "code": {
                "coding": [{"system": "http://snomed.info/sct", "code": "73211009", "display": "Diabetes mellitus"}]
            },
        }
        resp = client.post("/fhir/Condition", json=condition)
        assert resp.status_code == 201

    def test_search_conditions_by_patient(self, client):
        patient_id = self._create_patient(client)
        condition = {
            "resourceType": "Condition",
            "subject": {"reference": f"Patient/{patient_id}"},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "12345"}]},
        }
        client.post("/fhir/Condition", json=condition)

        resp = client.get(f"/fhir/Condition?patient={patient_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["type"] == "searchset"

    def test_unsupported_resource_type(self, client):
        resp = client.post("/fhir/Banana", json={"resourceType": "Banana"})
        assert resp.status_code == 400


class TestIpsOperation:
    def test_ips_for_patient(self, client):
        # Create patient
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "IpsTest", "given": ["Full"]}],
            "birthDate": "1990-01-01",
        }
        resp = client.post("/fhir/Patient", json=patient)
        patient_id = resp.get_json()["id"]

        # Add a condition
        condition = {
            "resourceType": "Condition",
            "subject": {"reference": f"Patient/{patient_id}"},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertension"}]},
        }
        client.post("/fhir/Condition", json=condition)

        # Generate IPS
        resp = client.get(f"/fhir/Patient/{patient_id}/$ips")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resourceType"] == "Bundle"
        assert data["type"] == "document"
        assert len(data["entry"]) >= 2  # Composition + Patient at minimum

    def test_ips_minimal_mode(self, client):
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "Minimal", "given": ["Mode"]}],
        }
        resp = client.post("/fhir/Patient", json=patient)
        patient_id = resp.get_json()["id"]

        resp = client.get(f"/fhir/Patient/{patient_id}/$ips?mode=minimal")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resourceType"] == "Bundle"

    def test_ips_nonexistent_patient(self, client):
        resp = client.get(f"/fhir/Patient/{uuid.uuid4()}/$ips")
        assert resp.status_code == 404
