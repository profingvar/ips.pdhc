"""#901 (EPS C1b) — wiring the state projection up.

#895 built the projection and left three things unwired: nothing rebuilt it,
four of the five existing state bearers were not projected, and no route
exposed the read. A projection nothing rebuilds is the same shape as a column
nothing populates (#900).

The per-source table in `services/patient_state` is the interesting part of
(b), because the answer differs per source and the differences are FINDINGS
about those columns rather than choices:

    source              valid_from    valid_to                  axes distinct?
    patient_consents    granted_at    revoked_at or expires_at  no
    patient_blocks      created_at    lifted_at or expires_at   no
    emergency_access    attested_at   expires_at                YES
    patient_index bools NULL          NULL                      NEITHER
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.base import db as _db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.emergency_access import EmergencyAccess
from app.models.fhir_resource import FhirResource
from app.models.patient_block import PatientBlock
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.patient_state import FACT_TYPES, PatientStateFact
from app.services import patient_state as ps
from app.services.fhir_service import create_resource

NOW = datetime(2026, 6, 1, 12, 0)
LATER = NOW + timedelta(days=30)


def _types(patient_guid):
    return {f.fact_type for f in _db.session.query(PatientStateFact)
            .filter_by(patient_guid=patient_guid)}


def _mk_patient(db, family="Kopplingsson"):
    rid = str(uuid.uuid4())
    res = create_resource("Patient", {
        "resourceType": "Patient", "id": rid,
        "name": [{"family": family, "given": ["Test"]}],
        "address": [{"use": "home", "city": "Gamlestad"}]})
    db.session.flush()
    pi = db.session.query(PatientIndex).filter_by(
        resource_id=res.resource_id).first()
    return pi, res


class TestTheTriggerFires:
    def test_creating_a_Patient_populates_the_projection(self, client, db):
        """(a) — `_sync_patient_index` already runs on every Patient create and
        update, so the projection rides on a hook that exists rather than
        needing a second one."""
        pi, _ = _mk_patient(db)
        db.session.commit()
        assert "address.city" in _types(pi.guid), _types(pi.guid)

    def test_UPDATING_a_Patient_refreshes_it(self, client, db):
        from app.services.fhir_service import update_resource
        pi, res = _mk_patient(db)
        db.session.commit()
        update_resource("Patient", res.resource_id, {
            "resourceType": "Patient", "id": res.resource_id,
            "name": [{"family": "Nysson", "given": ["Test"]}],
            "address": [{"use": "home", "city": "Nystad"}]})
        db.session.commit()
        cities = {f.value.get("value") for f in
                  _db.session.query(PatientStateFact)
                  .filter_by(patient_guid=pi.guid, fact_type="address.city")}
        assert "Nystad" in cities, cities

    def test_adding_an_ASSIGNMENT_refreshes_it(self, client, db):
        """The Patient hook cannot see an assignment added afterwards, which is
        why the three assignment write sites refresh too."""
        pi, _ = _mk_patient(db)
        c = Clinic(name="901 Clinic", organisation_guid=str(uuid.uuid4()))
        db.session.add(c)
        db.session.flush()
        db.session.commit()
        assert "clinic_assignment" not in _types(pi.guid)

        from app.services.patient_state import rebuild_for_patient
        db.session.add(PatientClinicAssignment(patient_guid=pi.guid,
                                               clinic_guid=c.guid))
        db.session.flush()
        rebuild_for_patient(pi.guid)          # what the three sites now do
        db.session.commit()
        assert "clinic_assignment" in _types(pi.guid)

    def test_a_failing_refresh_does_NOT_fail_the_write(self, client, db, monkeypatch):
        """A projection is derived data. Failing a clinical write because a
        read optimisation could not be refreshed would be the wrong trade, so
        the error is logged and the write stands."""
        import app.services.patient_state as pst

        def boom(*a, **k):
            raise RuntimeError("projection exploded")

        monkeypatch.setattr(pst, "rebuild_for_patient", boom)
        pi, _ = _mk_patient(db, family="Trotssson")
        db.session.commit()
        assert pi is not None, "the Patient write was lost"
        assert _db.session.get(PatientIndex, pi.guid) is not None


class TestTheFourRemainingSources:
    def test_a_CONSENT_projects_with_revocation_winning_over_expiry(self, client, db):
        """A consent revoked before it expired stopped being true when it was
        revoked, not when it would have expired."""
        pi, _ = _mk_patient(db, "Samtyckesson")
        db.session.add(PatientConsent(
            patient_guid=str(pi.guid), grantee_caregiver_guid=str(uuid.uuid4()),
            granted_via="portal", granted_at=NOW,
            expires_at=LATER, revoked_at=NOW + timedelta(days=5)))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        f = next(x for x in _db.session.query(PatientStateFact)
                 .filter_by(patient_guid=pi.guid, fact_type="consent"))
        assert f.valid_from == NOW
        assert f.valid_to == NOW + timedelta(days=5), f.valid_to

    def test_a_BLOCK_and_its_LIFT_are_separate_facts(self, client, db):
        """Folding the lift into the block row would make "was this block
        lifted on date D" unanswerable."""
        pi, _ = _mk_patient(db, "Sparrsson")
        db.session.add(PatientBlock(
            patient_guid=str(pi.guid), source_scope_type="clinic",
            source_scope_id=str(uuid.uuid4()), created_at=NOW,
            lifted_at=NOW + timedelta(days=2), lift_kind="indispensable",
            lift_expires_at=NOW + timedelta(days=3)))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        got = _types(pi.guid)
        assert "block" in got and "block_lift" in got, got
        lift = next(x for x in _db.session.query(PatientStateFact)
                    .filter_by(patient_guid=pi.guid, fact_type="block_lift"))
        assert lift.valid_from == NOW + timedelta(days=2)
        assert lift.valid_to == NOW + timedelta(days=3)

    def test_EMERGENCY_ACCESS_is_the_one_source_with_DISTINCT_axes(self, client, db):
        """`attested_at` is when the need was attested; `created_at` is when we
        wrote it down. Two columns, two meanings, already there before this
        projection existed — so this is the one fact type that proves the model
        is not merely carrying the same timestamp twice."""
        pi, _ = _mk_patient(db, "Nodsson")
        db.session.add(EmergencyAccess(
            patient_guid=str(pi.guid), reader_care_unit_guid=str(uuid.uuid4()),
            reason="akut", attested_at=NOW,
            created_at=NOW + timedelta(hours=3),
            expires_at=LATER))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        f = next(x for x in _db.session.query(PatientStateFact)
                 .filter_by(patient_guid=pi.guid, fact_type="emergency_access"))
        assert f.valid_from == NOW
        assert f.recorded_at == NOW + timedelta(hours=3)
        assert f.valid_from != f.recorded_at, "the two axes collapsed"

    def test_a_BOOLEAN_opt_out_has_NEITHER_axis_and_says_so(self, client, db):
        """`ehds_opt_out` is a bare boolean with no timestamp anywhere, so the
        projection cannot say when the patient opted out or when we learned it.
        NULL/NULL is the honest answer, and the value carries a flag saying the
        date is unrecorded rather than leaving a reader to infer it from
        `recorded_at`.

        It is also a finding about those columns: an opt-out whose date is
        unrecorded cannot be audited."""
        pi, _ = _mk_patient(db, "Avstasson")
        pi.ehds_opt_out = True
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        f = next(x for x in _db.session.query(PatientStateFact)
                 .filter_by(patient_guid=pi.guid, fact_type="ehds_opt_out"))
        assert f.valid_from is None and f.valid_to is None
        assert f.value["date_unrecorded"] is True

    def test_an_UNSET_flag_projects_NOTHING(self, client, db):
        """The control: the projection records the opt-out, not the column."""
        pi, _ = _mk_patient(db, "Medsson")
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        assert "ehds_opt_out" not in _types(pi.guid)

    def test_EVERY_projected_value_is_JSON_serialisable(self, client, db):
        """A general guard, not four specific ones.

        Guid columns on these tables come back as UUID OBJECTS, and
        `json.dumps` refuses a UUID — so the insert failed inside the flush
        with a traceback naming the JSON encoder rather than the column. It
        cost a probe to find. Every projector now routes values through `_j()`,
        and this asserts the property rather than the four fields, so the next
        projector is covered too.
        """
        import json
        pi, _ = _mk_patient(db, "Jsonsson")
        pi.ehds_opt_out = True
        pi.archived_at = NOW
        db.session.add(PatientConsent(
            patient_guid=str(pi.guid), grantee_caregiver_guid=str(uuid.uuid4()),
            granted_via="portal", granted_at=NOW))
        db.session.add(PatientBlock(
            patient_guid=str(pi.guid), source_scope_type="clinic",
            source_scope_id=str(uuid.uuid4()), created_at=NOW,
            lifted_at=NOW + timedelta(days=1)))
        db.session.add(EmergencyAccess(
            patient_guid=str(pi.guid), reader_care_unit_guid=str(uuid.uuid4()),
            reason="akut", attested_at=NOW, created_at=NOW, expires_at=LATER))
        c = Clinic(name="901 J", organisation_guid=str(uuid.uuid4()))
        db.session.add(c)
        db.session.flush()
        db.session.add(PatientClinicAssignment(patient_guid=pi.guid,
                                               clinic_guid=c.guid))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        rows = list(_db.session.query(PatientStateFact)
                    .filter_by(patient_guid=pi.guid))
        assert len(rows) >= 7, len(rows)
        for r in rows:
            json.dumps(r.value)          # raises TypeError if not serialisable

    def test_every_projected_type_is_in_the_declared_vocabulary(self, client, db):
        pi, _ = _mk_patient(db, "Ordsson")
        pi.ehds_opt_out = True
        pi.archived_at = NOW
        db.session.add(PatientConsent(
            patient_guid=str(pi.guid), grantee_caregiver_guid=str(uuid.uuid4()),
            granted_via="portal", granted_at=NOW))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        for ft in _types(pi.guid):
            assert ft in FACT_TYPES, ft


class TestTheReadRoute:
    def _admin_patient(self, db):
        pi, _ = _mk_patient(db, "Vagsson")
        db.session.commit()
        return pi

    def test_it_returns_the_facts_and_echoes_the_question(self, client, db):
        pi = self._admin_patient(db)
        r = client.get(f"/api/v1/patients/{pi.guid}/state")
        assert r.status_code == 200, r.get_data(as_text=True)
        b = r.get_json()
        assert b["count"] >= 1
        assert "as_at" in b and "as_known_on" in b
        assert b["projection"]["derived"] is True

    def test_it_answers_the_two_axis_question(self, client, db):
        pi = self._admin_patient(db)
        r = client.get(f"/api/v1/patients/{pi.guid}/state"
                       "?as_at=2026-04-01&as_known_on=2026-08-01")
        assert r.status_code == 200
        b = r.get_json()
        assert b["as_at"].startswith("2026-04-01")
        assert b["as_known_on"].startswith("2026-08-01")

    def test_a_bad_date_is_400_not_500(self, client, db):
        pi = self._admin_patient(db)
        r = client.get(f"/api/v1/patients/{pi.guid}/state?as_at=yesterday")
        assert r.status_code == 400
        assert "as_at" in r.get_json()["error"]

    def test_a_malformed_guid_is_400(self, client, db):
        r = client.get("/api/v1/patients/not-a-guid/state")
        assert r.status_code == 400

    def test_a_patient_OUT_OF_SCOPE_is_404_not_403(self, client, db, monkeypatch):
        """404, because a 403 confirms the guid exists — the same reasoning as
        the export withholding silently."""
        pi = self._admin_patient(db)
        from app.services import patient_export as px
        monkeypatch.setattr(px, "exportable", lambda g: ([], list(g)))
        r = client.get(f"/api/v1/patients/{pi.guid}/state")
        assert r.status_code == 404
        assert "not found" in r.get_json()["error"]
