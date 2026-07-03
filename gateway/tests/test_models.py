"""Tests for SQLAlchemy models — Step 2.d."""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.base import db as _db
from app.models.user import User
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.api_key import ApiKey
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.audit_log import AuditLog
from app.models.capability_statement import CapabilityStatement


class TestUserModel:
    def test_create_user(self, client, db):
        user = User(username="testuser", display_name="Test User", role="operator")
        db.session.add(user)
        db.session.flush()
        assert user.guid is not None
        assert isinstance(user.guid, uuid.UUID)
        assert user.username == "testuser"
        assert user.is_active is True
        assert user.is_superuser is False

    def test_user_to_dict(self, client, db):
        user = User(username="dictuser", role="admin")
        db.session.add(user)
        db.session.flush()
        d = user.to_dict()
        assert d["username"] == "dictuser"
        assert d["role"] == "admin"
        assert "guid" in d
        assert "password_hash" not in d

    def test_username_unique(self, client, db):
        u1 = User(username="unique", role="operator")
        u2 = User(username="unique", role="admin")
        db.session.add(u1)
        db.session.flush()
        db.session.add(u2)
        with pytest.raises(Exception):
            db.session.flush()


class TestClinicModel:
    def test_create_clinic(self, client, db):
        clinic = Clinic(name="Test Clinic")
        db.session.add(clinic)
        db.session.flush()
        assert clinic.guid is not None
        assert clinic.is_active is True

    def test_user_clinic_assignment(self, client, db):
        user = User(username="clinicuser", role="operator")
        clinic = Clinic(name="Assigned Clinic")
        db.session.add_all([user, clinic])
        db.session.flush()

        assignment = UserClinicAssignment(
            user_guid=user.guid, clinic_guid=clinic.guid, role="member"
        )
        db.session.add(assignment)
        db.session.flush()
        assert assignment.guid is not None


class TestFhirResourceModel:
    def test_create_fhir_resource(self, client, db):
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient", "name": [{"family": "Test"}]},
        )
        db.session.add(res)
        db.session.flush()
        assert res.guid is not None
        assert res.version_id == 1
        assert res.status == "active"


class TestPatientIndexModel:
    def test_create_patient_index(self, client, db):
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(
            fhir_resource_guid=res.guid,
            resource_id=res.resource_id,
            family_name="Svensson",
            given_name="Anna",
        )
        db.session.add(pi)
        db.session.flush()
        assert pi.guid is not None
        assert pi.family_name == "Svensson"

    def test_reform_consent_flags_default(self, client, db):
        """D1 (#404): the two genuinely-new consent flags default to False and
        the research list defaults to empty in to_dict()."""
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=res.resource_id)
        db.session.add(pi)
        db.session.flush()

        assert pi.ehds_opt_out is False
        assert pi.quality_registry_opt_out is False
        assert pi.consented_research_projects is None

        d = pi.to_dict()
        assert d["ehds_opt_out"] is False
        assert d["quality_registry_opt_out"] is False
        assert d["consented_research_projects"] == []  # None -> [] in to_dict

    def test_reform_consent_flags_set(self, client, db):
        """D1 (#404): flags round-trip and the research-project list persists."""
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        proj = str(uuid.uuid4())
        pi = PatientIndex(
            fhir_resource_guid=res.guid,
            resource_id=res.resource_id,
            ehds_opt_out=True,
            quality_registry_opt_out=True,
            consented_research_projects=[proj],
        )
        db.session.add(pi)
        db.session.flush()

        d = pi.to_dict()
        assert d["ehds_opt_out"] is True
        assert d["quality_registry_opt_out"] is True
        assert d["consented_research_projects"] == [proj]

    def test_primary_care_unit_guids_from_assignments(self, client, db):
        """D1 (#404): primary_care_unit_guids() derives Zone-1 units from the
        existing PatientClinicAssignment rows, not a new column."""
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=res.resource_id)
        db.session.add(pi)
        db.session.flush()

        assert pi.primary_care_unit_guids() == []

        clinic = Clinic(name="Vårdcentral Nord")
        db.session.add(clinic)
        db.session.flush()
        db.session.add(
            PatientClinicAssignment(patient_guid=pi.guid, clinic_guid=clinic.guid)
        )
        db.session.flush()
        db.session.refresh(pi)

        assert pi.primary_care_unit_guids() == [str(clinic.guid)]


class TestIpsCardModel:
    def test_create_ips_card(self, client, db):
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=res.resource_id)
        db.session.add(pi)
        db.session.flush()

        card = IpsCard(patient_guid=pi.guid, mode="full")
        db.session.add(card)
        db.session.flush()
        assert card.guid is not None
        assert card.status == "active"
        assert card.mode == "full"


class TestIpsSnapshotModel:
    def test_create_snapshot(self, client, db):
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=res.resource_id)
        db.session.add(pi)
        db.session.flush()

        card = IpsCard(patient_guid=pi.guid)
        db.session.add(card)
        db.session.flush()

        snapshot = IpsSnapshot(
            card_guid=card.guid,
            bundle_json={"resourceType": "Bundle", "entry": []},
            composition_date=datetime.now(timezone.utc),
            mode="full",
            resource_count=0,
        )
        db.session.add(snapshot)
        db.session.flush()
        assert snapshot.guid is not None

    def test_snapshot_to_dict_excludes_bundle(self, client, db):
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=res.resource_id)
        db.session.add(pi)
        db.session.flush()

        card = IpsCard(patient_guid=pi.guid)
        db.session.add(card)
        db.session.flush()

        snapshot = IpsSnapshot(
            card_guid=card.guid,
            bundle_json={"resourceType": "Bundle"},
            composition_date=datetime.now(timezone.utc),
            mode="full",
        )
        db.session.add(snapshot)
        db.session.flush()

        d = snapshot.to_dict(include_bundle=False)
        assert "bundle_json" not in d

        d_with = snapshot.to_dict(include_bundle=True)
        assert "bundle_json" in d_with


class TestPushModels:
    def test_create_destination(self, client, db):
        dest = PushDestination(
            name="Test FHIR Server",
            destination_type="fhir_endpoint",
            endpoint_url="https://fhir.example.com/Bundle",
        )
        db.session.add(dest)
        db.session.flush()
        assert dest.guid is not None
        assert dest.is_active is True

    def test_create_push_job(self, client, db):
        res = FhirResource(
            resource_type="Patient",
            resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"},
        )
        db.session.add(res)
        db.session.flush()

        pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=res.resource_id)
        db.session.add(pi)
        db.session.flush()

        card = IpsCard(patient_guid=pi.guid)
        db.session.add(card)
        db.session.flush()

        snapshot = IpsSnapshot(
            card_guid=card.guid,
            bundle_json={},
            composition_date=datetime.now(timezone.utc),
            mode="full",
        )
        db.session.add(snapshot)
        db.session.flush()

        dest = PushDestination(
            name="Dest", destination_type="webhook", endpoint_url="https://example.com"
        )
        db.session.add(dest)
        db.session.flush()

        job = PushJob(snapshot_guid=snapshot.guid, destination_guid=dest.guid)
        db.session.add(job)
        db.session.flush()
        assert job.status == "queued"
        assert job.attempts == 0


class TestAuditLogModel:
    def test_create_audit_entry(self, client, db):
        entry = AuditLog(
            event_type="test_event",
            actor_type="system",
            actor_label="test",
            request_path="/test",
            request_method="GET",
        )
        db.session.add(entry)
        db.session.flush()
        assert entry.guid is not None
        d = entry.to_dict()
        assert d["event_type"] == "test_event"


class TestCapabilityStatementModel:
    def test_create_capability_statement(self, client, db):
        cs = CapabilityStatement(
            resource_json={"resourceType": "CapabilityStatement", "status": "active"},
            version="0.1.0",
        )
        db.session.add(cs)
        db.session.flush()
        assert cs.is_current is True
