"""IPS Renov 8 (#204) — cross-caregiver block check.

Verifies:
- The pre-existing PatientBlock + create/list/lift surface accepts
  ``source_scope_type='caregiver'`` end-to-end (the model has supported
  it since #197; this test pins down the round-trip).
- ``GET /api/v1/patients/<guid>/blocks/check`` consults BOTH clinic-
  level and caregiver-level blocks and returns the correct verdict.
- A caregiver-level block hides reads from any clinic under that
  caregiver — the consumer doesn't have to enumerate the clinic set.
- Lifting a caregiver-level block flips the verdict back to "not
  blocked" for the whole caregiver subtree.
- Auth: caller need not have a PatientClinicAssignment to the patient;
  the predicate is consulted on cross-caregiver reads where the
  relationship is the very thing being protected.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_index import (
    PatientClinicAssignment, PatientIndex,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def world(client, db):
    """Patient, clinic A and clinic B both under caregiver G, plus
    SU + staff for impersonation."""
    fhir = FhirResource(
        resource_type="Patient",
        resource_id=str(uuid.uuid4()),
        resource_json={"resourceType": "Patient"},
    )
    db.session.add(fhir)
    db.session.flush()
    patient = PatientIndex(
        fhir_resource_guid=fhir.guid,
        resource_id=str(uuid.uuid4()),
        family_name="Larsson",
        given_name="Lina",
    )
    clinic_a = Clinic(name="Caregiver-G Clinic A", is_active=True)
    clinic_b = Clinic(name="Caregiver-G Clinic B", is_active=True)
    db.session.add_all([patient, clinic_a, clinic_b])
    db.session.flush()
    # Patient has a relationship to clinic A (so block-create works
    # via the same staff path #197 set up).
    db.session.add(PatientClinicAssignment(
        patient_guid=patient.guid, clinic_guid=clinic_a.guid,
    ))
    su = User(
        username=f"check_su_{uuid.uuid4().hex[:8]}",
        display_name="SU", role="admin",
        is_active=True, is_superuser=True,
    )
    db.session.add(su)
    db.session.commit()

    # A "caregiver" guid lives in SSO; IPS doesn't validate it against
    # any local table. We just need a stable UUID for tests.
    caregiver_g = str(uuid.uuid4())

    return {
        "patient": patient,
        "clinic_a": clinic_a,
        "clinic_b": clinic_b,
        "caregiver_g": caregiver_g,
        "su": su,
    }


@pytest.fixture
def silence_webhook(monkeypatch):
    monkeypatch.setattr(
        "app.api.blocks_routes._emit_block_webhook",
        lambda event, block: None,
    )


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


# ---------------------------------------------------------------------------
# Existing block surface accepts caregiver-scope end-to-end
# ---------------------------------------------------------------------------

class TestCaregiverScopeRoundTrip:
    def test_create_list_lift_caregiver_block(
        self, client, db, world, silence_webhook,
    ):
        # Create a caregiver-level block.
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
                "reason": "patient blocks the whole caregiver",
            },
        )
        assert r.status_code == 201, r.get_json()
        block = r.get_json()
        assert block["source_scope_type"] == "caregiver"
        assert block["source_scope_id"] == world["caregiver_g"]
        block_guid = block["guid"]

        # List shows it.
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
        )
        assert r.status_code == 200
        items = r.get_json()["items"]
        assert any(
            b.get("source_scope_id") == world["caregiver_g"]
            for b in items
        )

        # Lift (consent path — patient changed their mind).
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks/"
            f"{block_guid}/lift",
            json={
                "lift_kind": "consent",
                "reason": "patient withdraws the block",
            },
        )
        assert r.status_code == 200, r.get_json()

        # Audit chain.
        events = (
            db.session.query(AuditLog)
            .filter_by(resource_type="PatientBlock")
            .order_by(AuditLog.created_at.asc())
            .all()
        )
        types = [e.event_type for e in events]
        assert "block.created" in types
        assert "block.lifted" in types


# ---------------------------------------------------------------------------
# /blocks/check basic shape
# ---------------------------------------------------------------------------

class TestCheckShape:
    def test_no_blocks_is_not_blocked(self, client, db, world):
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["is_blocked"] is False
        assert body["blocking_scopes"] == []
        assert body["source_caregiver_id"] is None

    def test_missing_clinic_id_is_400(self, client, db, world):
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
        )
        assert r.status_code == 400
        assert "source_clinic_id" in r.get_json()["error"]

    def test_bad_clinic_id_shape_is_400(self, client, db, world):
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={"source_clinic_id": "not-a-uuid"},
        )
        assert r.status_code == 400

    def test_bad_caregiver_id_shape_is_400(self, client, db, world):
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
                "source_caregiver_id": "not-a-uuid",
            },
        )
        assert r.status_code == 400

    def test_unknown_patient_is_404(self, client, db, world):
        r = client.get(
            f"/api/v1/patients/{uuid.uuid4()}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
            },
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Clinic-level block semantics
# ---------------------------------------------------------------------------

class TestClinicLevelBlock:
    def test_clinic_block_blocks_only_that_clinic(
        self, client, db, world, silence_webhook,
    ):
        # Block clinic A.
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "clinic",
                "source_scope_id": str(world["clinic_a"].guid),
            },
        )
        assert r.status_code == 201

        # Check from clinic A's perspective — blocked.
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
                "source_caregiver_id": world["caregiver_g"],
            },
        )
        body = r.get_json()
        assert body["is_blocked"] is True
        assert len(body["blocking_scopes"]) == 1
        assert body["blocking_scopes"][0]["scope_type"] == "clinic"

        # Clinic B (same caregiver) — NOT blocked.
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_b"].guid),
                "source_caregiver_id": world["caregiver_g"],
            },
        )
        body = r.get_json()
        assert body["is_blocked"] is False
        assert body["blocking_scopes"] == []


# ---------------------------------------------------------------------------
# Caregiver-level block semantics — the core ticket #204 behaviour
# ---------------------------------------------------------------------------

class TestCaregiverLevelBlock:
    def test_caregiver_block_hides_all_clinics_under_caregiver(
        self, client, db, world, silence_webhook,
    ):
        # Block caregiver G outright.
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
            },
        )
        assert r.status_code == 201

        # Both clinic A AND clinic B (under caregiver G) come back blocked.
        for clinic in (world["clinic_a"], world["clinic_b"]):
            r = client.get(
                f"/api/v1/patients/{world['patient'].guid}/blocks/check",
                query_string={
                    "source_clinic_id": str(clinic.guid),
                    "source_caregiver_id": world["caregiver_g"],
                },
            )
            body = r.get_json()
            assert body["is_blocked"] is True, (
                f"clinic {clinic.name} should be blocked via caregiver G"
            )
            assert (
                body["blocking_scopes"][0]["scope_type"] == "caregiver"
            )
            assert (
                body["blocking_scopes"][0]["scope_id"]
                == world["caregiver_g"]
            )

    def test_caregiver_block_does_not_hide_other_caregivers_clinics(
        self, client, db, world, silence_webhook,
    ):
        # Block caregiver G.
        client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
            },
        )
        # A clinic under some OTHER caregiver — must NOT be blocked.
        unrelated_clinic = uuid.uuid4()
        unrelated_caregiver = str(uuid.uuid4())
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(unrelated_clinic),
                "source_caregiver_id": unrelated_caregiver,
            },
        )
        body = r.get_json()
        assert body["is_blocked"] is False
        assert body["blocking_scopes"] == []

    def test_check_without_caregiver_id_ignores_caregiver_blocks(
        self, client, db, world, silence_webhook,
    ):
        """A consumer that didn't supply source_caregiver_id (legacy
        path) only learns about clinic-level blocks. This is
        backwards-compatible: pre-#204 consumers still get the right
        clinic answer, just without the caregiver-tree dimension."""
        client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
            },
        )
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
                # source_caregiver_id deliberately omitted.
            },
        )
        body = r.get_json()
        # Consumer didn't supply the caregiver context, so we can't
        # apply the caregiver-level block from this side. False here is
        # the safe default — legacy callers see what they always saw.
        assert body["is_blocked"] is False


# ---------------------------------------------------------------------------
# Lift propagates through the caregiver subtree
# ---------------------------------------------------------------------------

class TestLiftCaregiverTree:
    def test_lifting_caregiver_block_clears_for_whole_tree(
        self, client, db, world, silence_webhook,
    ):
        # Block caregiver G.
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
            },
        )
        assert r.status_code == 201
        block_guid = r.get_json()["guid"]

        # Before lift: both clinics blocked via caregiver G.
        for clinic in (world["clinic_a"], world["clinic_b"]):
            r = client.get(
                f"/api/v1/patients/{world['patient'].guid}/blocks/check",
                query_string={
                    "source_clinic_id": str(clinic.guid),
                    "source_caregiver_id": world["caregiver_g"],
                },
            )
            assert r.get_json()["is_blocked"] is True

        # Lift the caregiver-level block (consent path — permanent).
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks/"
            f"{block_guid}/lift",
            json={"lift_kind": "consent", "reason": "ok"},
        )
        assert r.status_code == 200

        # After lift: BOTH clinics unblocked. The whole caregiver tree
        # is cleared by the single lift action.
        for clinic in (world["clinic_a"], world["clinic_b"]):
            r = client.get(
                f"/api/v1/patients/{world['patient'].guid}/blocks/check",
                query_string={
                    "source_clinic_id": str(clinic.guid),
                    "source_caregiver_id": world["caregiver_g"],
                },
            )
            body = r.get_json()
            assert body["is_blocked"] is False, (
                f"clinic {clinic.name} should be cleared after the "
                "caregiver-level lift"
            )


# ---------------------------------------------------------------------------
# Both scopes blocked at once — either is sufficient
# ---------------------------------------------------------------------------

class TestCombinedBlocks:
    def test_both_clinic_and_caregiver_blocked_returns_both_scopes(
        self, client, db, world, silence_webhook,
    ):
        # Block at both levels.
        client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "clinic",
                "source_scope_id": str(world["clinic_a"].guid),
            },
        )
        client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
            },
        )
        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
                "source_caregiver_id": world["caregiver_g"],
            },
        )
        body = r.get_json()
        assert body["is_blocked"] is True
        # Both scopes surface — consumer can pick whichever lift it
        # consults.
        scope_types = {
            s["scope_type"] for s in body["blocking_scopes"]
        }
        assert scope_types == {"clinic", "caregiver"}


# ---------------------------------------------------------------------------
# Indispensable-care lift surfaces in the check response
# ---------------------------------------------------------------------------

class TestLiftSurfaces:
    def test_indispensable_lift_surfaces_in_check(
        self, client, db, world, silence_webhook,
    ):
        # Block + indispensable_care lift on the same caregiver-level row.
        r = client.post(
            f"/api/v1/patients/{world['patient'].guid}/blocks",
            json={
                "source_scope_type": "caregiver",
                "source_scope_id": world["caregiver_g"],
            },
        )
        block_guid = r.get_json()["guid"]
        concepts = [str(uuid.uuid4())]
        r = client.post(
            f"/api/v1/admin/blocks/{block_guid}/lift",
            json={
                "reason": "ER admission",
                "concept_guids": concepts,
                "expires_in": 60,
            },
        )
        assert r.status_code == 200

        r = client.get(
            f"/api/v1/patients/{world['patient'].guid}/blocks/check",
            query_string={
                "source_clinic_id": str(world["clinic_a"].guid),
                "source_caregiver_id": world["caregiver_g"],
            },
        )
        body = r.get_json()
        # The block is lifted (lift_expires_at in the future), so the
        # current verdict is "not blocked" — but the consumer still
        # gets the lift metadata so it can apply the mechanical filter
        # downstream (concept_guids + dates).
        assert body["is_blocked"] is False
        assert len(body["blocking_scopes"]) == 1
        scope = body["blocking_scopes"][0]
        assert scope["scope_type"] == "caregiver"
        assert scope["lift_kind"] == "indispensable_care"
        assert scope["lift_concept_guids"] == concepts
        assert scope["lift_expires_at"] is not None
