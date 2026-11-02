"""#895 (EPS C1) — the bitemporal patient-state projection.

Decided by #894 (EPS A2) option c: the write path stays `fhir_resources`,
append-only and already built, and this is a DERIVED projection for reading.

The tests that matter are the ones a single axis cannot pass. A patient moves
in March and tells us in July; between those dates the register is WRONG, and
both "where did they live in March" and "what did we believe in April" are
legitimate questions with different answers. `TestTheMarchJulyCase` is the
whole reason this table has four timestamp columns instead of two.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.patient_state import FACT_TYPES, PatientStateFact
from app.services import patient_state as ps


def T(month, day=1):
    """NAIVE UTC, deliberately, and only because of the test backend.

    The suite runs SQLite, which stores no timezone: an aware datetime goes in
    and a naive one comes back. Mixing the two does not merely break an
    assertion — it corrupts the SQL comparison, because the stored text and the
    bound parameter are formatted differently, and `as_at=JANUARY` then matched
    a fact whose validity starts in MARCH.

    Production is Postgres with `DateTime(timezone=True)` columns and the
    service passes `datetime.now(timezone.utc)`, so both sides are aware there
    and consistent. The bitemporal read is additionally proven against real
    Postgres (see the module's companion proof in changed_files.md), because a
    time comparison verified only on SQLite is not verified.
    """
    return datetime(2026, month, day, 12, 0)


JAN, MAR, APR, JUL, AUG = T(1), T(3), T(4), T(7), T(8)


def _patient(db, family="Flyttsson"):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid},
                       created_at=JAN)
    db.session.add(res)
    db.session.flush()
    pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                      family_name=family, given_name="Test")
    db.session.add(pi)
    db.session.flush()
    res.patient_guid = pi.guid
    db.session.flush()
    return pi, res


def _version(db, pi, rid, body, *, version, created_at):
    r = FhirResource(resource_type="Patient", resource_id=rid,
                     version_id=version, resource_json=body,
                     patient_guid=pi.guid, created_at=created_at)
    db.session.add(r)
    db.session.flush()
    return r


def _facts(pi, **kw):
    return {(f.fact_type, str(f.value.get("value"))) for f in ps.state_at(pi.guid, **kw)}


class TestDerivation:
    def test_demographics_are_projected_from_the_patient_resource(self, client, db):
        pi, res = _patient(db)
        res.resource_json = {
            "resourceType": "Patient", "id": res.resource_id,
            "name": [{"family": "Flyttsson", "given": ["Anna"]}],
            "address": [{"use": "home", "city": "Gamlestad", "country": "SE"}],
            "telecom": [{"system": "phone", "value": "+46701111111", "use": "mobile"}],
        }
        db.session.flush()
        n = ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        assert n > 0
        got = {f.fact_type for f in ps.state_at(pi.guid)}
        assert {"name.family", "name.given", "address.city",
                "address.country", "telecom"} <= got, got

    def test_every_fact_type_is_in_the_declared_vocabulary(self, client, db):
        """A projection whose keys are whatever the projector happened to emit
        cannot be queried by anyone who did not write the projector."""
        pi, res = _patient(db)
        res.resource_json = {
            "resourceType": "Patient", "id": res.resource_id,
            "name": [{"family": "X", "given": ["Y"]}],
            "address": [{"city": "Z", "country": "SE", "postalCode": "12345",
                         "line": ["Gata 1"]}],
            "telecom": [{"system": "phone", "value": "+46"}],
            "contact": [{"relationship": [{"text": "sister"}]}],
        }
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        for f in _db.session.query(PatientStateFact).filter_by(patient_guid=pi.guid):
            assert f.fact_type in FACT_TYPES, f.fact_type

    def test_the_cardinality_is_1_to_N_not_1_to_1(self, client, db):
        """The operator's correction to the original framing. A patient has
        several addresses, and the projection must carry all of them."""
        pi, res = _patient(db)
        res.resource_json = {
            "resourceType": "Patient", "id": res.resource_id,
            "address": [{"use": "home", "city": "Gamlestad", "country": "SE"},
                        {"use": "work", "city": "Nystad", "country": "SE"}],
        }
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        cities = sorted(f.value["value"] for f in ps.state_at(pi.guid)
                        if f.fact_type == "address.city")
        assert cities == ["Gamlestad", "Nystad"], cities


class TestTheTwoAxesAreNotTheSame:
    def test_validity_is_NULL_when_no_period_and_that_is_NOT_recorded_at(self, client, db):
        """The single-axis mistake, pinned. NULL validity means "we do not know
        when this became true" — a different claim from "it became true when we
        recorded it". Measured: no Patient element in this service carries a
        period, so this is the state of every demographic fact today."""
        pi, res = _patient(db)
        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Gamlestad"}]}
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        f = next(x for x in ps.state_at(pi.guid) if x.fact_type == "address.city")
        assert f.valid_from is None, "validity was invented from a record time"
        assert f.recorded_at is not None, "record time must still be set"

    def test_validity_IS_taken_from_a_period_when_present(self, client, db):
        pi, res = _patient(db)
        res.resource_json = {
            "resourceType": "Patient", "id": res.resource_id,
            "address": [{"city": "Nystad",
                         "period": {"start": MAR.isoformat()}}]}
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        f = next(x for x in ps.state_at(pi.guid) if x.fact_type == "address.city")
        assert f.valid_from == MAR, f.valid_from

    def test_a_versions_record_interval_ENDS_where_the_next_begins(self, client, db):
        pi, res = _patient(db)
        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Gamlestad"}]}
        res.status = "superseded"
        db.session.flush()
        _version(db, pi, res.resource_id,
                 {"resourceType": "Patient", "id": res.resource_id,
                  "address": [{"city": "Nystad"}]},
                 version=2, created_at=JUL)
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        rows = sorted(_db.session.query(PatientStateFact)
                      .filter_by(patient_guid=pi.guid, fact_type="address.city"),
                      key=lambda r: r.recorded_at)
        assert len(rows) == 2, [r.value for r in rows]
        assert rows[0].recorded_until == rows[1].recorded_at == JUL


class TestTheMarchJulyCase:
    """The register was WRONG between March and July, and both questions about
    that window have answers. This is what one axis cannot express."""

    def _setup(self, db):
        pi, res = _patient(db)
        # v1, recorded in JANUARY: the patient lives in Gamlestad.
        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Gamlestad"}]}
        res.status = "superseded"
        db.session.flush()
        # v2, recorded in JULY, saying the patient has lived in Nystad SINCE MARCH.
        _version(db, pi, res.resource_id,
                 {"resourceType": "Patient", "id": res.resource_id,
                  "address": [{"city": "Nystad",
                               "period": {"start": MAR.isoformat()}}]},
                 version=2, created_at=JUL)
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        return pi

    def test_in_APRIL_we_believed_Gamlestad(self, client, db):
        pi = self._setup(db)
        got = _facts(pi, as_at=APR, as_known_on=APR)
        assert ("address.city", "Gamlestad") in got, got
        assert ("address.city", "Nystad") not in got, got

    def test_in_AUGUST_we_know_they_lived_in_Nystad_in_APRIL(self, client, db):
        """Same validity date, different knowledge date, different answer.
        A single-axis store cannot hold both of these."""
        pi = self._setup(db)
        got = _facts(pi, as_at=APR, as_known_on=AUG)
        assert ("address.city", "Nystad") in got, got

    def test_by_AUGUST_we_know_NOTHING_about_JANUARY_and_that_is_correct(self, client, db):
        """A finding, not a gap — and it surprised the author of this test.

        In August the current record is v2, which asserts Nystad FROM MARCH and
        says nothing about January. v1 (Gamlestad, unbounded) stopped being
        current knowledge in July. So "as known on August, where did they live
        in January?" has no answer, and the projection correctly returns none.

        The cause is that FHIR versioning replaces the WHOLE RESOURCE rather
        than one fact: a new version carrying a narrower validity silently
        drops what the previous version asserted about earlier dates. The
        earlier belief is not lost from the store — the row is still there with
        `recorded_until` set — it is reachable only by asking what we believed
        THEN, which the test below does.

        Worth knowing before anyone builds a "current state" view on top of
        this and wonders why old addresses vanish.
        """
        pi = self._setup(db)
        got = _facts(pi, as_at=JAN, as_known_on=AUG)
        assert ("address.city", "Gamlestad") not in got, got
        assert ("address.city", "Nystad") not in got, got

    def test_the_JANUARY_belief_is_still_reachable_by_asking_APRIL(self, client, db):
        """The row was never deleted; only superseded. This is the half of
        bitemporality `fhir_resources` already gave us, and it is why the
        append-only write path mattered."""
        pi = self._setup(db)
        got = _facts(pi, as_at=JAN, as_known_on=APR)
        assert ("address.city", "Gamlestad") in got, got

    def test_the_unknown_bound_is_RETURNED_not_filled_in(self, client, db):
        """A caller must be able to see that a bound is unknown. Inventing one
        would make an unknown start indistinguishable from a known one."""
        pi = self._setup(db)
        g = next(f for f in ps.state_at(pi.guid, as_at=JAN, as_known_on=APR)
                 if f.value.get("value") == "Gamlestad")
        assert g.valid_from is None
        assert g.to_dict()["valid_from"] is None


class TestClinicAssignmentIsTheOneSourceWithRealValidity:
    def test_an_ENDED_assignment_is_absent_NOW_and_present_THEN(self, client, db):
        """After #891 this table carries assigned_at and ended_at, so it is the
        one fact type where both validity bounds are real data rather than
        NULL."""
        pi, res = _patient(db)
        c = Clinic(name="C1 Clinic", organisation_guid=str(uuid.uuid4()))
        db.session.add(c)
        db.session.flush()
        db.session.add(PatientClinicAssignment(
            patient_guid=pi.guid, clinic_guid=c.guid,
            assigned_at=JAN, ended_at=APR))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()

        then = [f for f in ps.state_at(pi.guid, as_at=MAR, as_known_on=AUG)
                if f.fact_type == "clinic_assignment"]
        now = [f for f in ps.state_at(pi.guid, as_at=JUL, as_known_on=AUG)
               if f.fact_type == "clinic_assignment"]
        assert len(then) == 1, then
        assert now == [], now

    def test_its_two_axes_COINCIDE_and_that_is_the_sources_limit(self, client, db):
        """Said out loud in the code and asserted here: the source carries one
        timestamp, so "when it began" and "when we wrote it down" cannot be
        told apart for this fact type. A reader comparing the columns would
        otherwise conclude the model conflates them."""
        pi, res = _patient(db)
        c = Clinic(name="C1b", organisation_guid=str(uuid.uuid4()))
        db.session.add(c)
        db.session.flush()
        db.session.add(PatientClinicAssignment(
            patient_guid=pi.guid, clinic_guid=c.guid, assigned_at=JAN))
        db.session.commit()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        f = next(x for x in ps.state_at(pi.guid) if x.fact_type == "clinic_assignment")
        assert f.valid_from == f.recorded_at == JAN


class TestItIsAProjectionNotASource:
    def test_rebuild_is_TOTAL_so_a_stale_fact_disappears(self, client, db):
        pi, res = _patient(db)
        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Gamlestad"}]}
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        assert any(f.value.get("value") == "Gamlestad" for f in ps.state_at(pi.guid))

        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Nystad"}]}
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        cities = {f.value.get("value") for f in ps.state_at(pi.guid)}
        assert cities == {"Nystad"}, cities

    def test_rebuild_is_idempotent(self, client, db):
        """A projection patched incrementally drifts from its sources; one that
        is re-derived cannot."""
        pi, res = _patient(db)
        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Gamlestad"}],
                             "telecom": [{"system": "phone", "value": "+46"}]}
        db.session.flush()
        a = ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        b = ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        assert a == b
        assert (_db.session.query(PatientStateFact)
                .filter_by(patient_guid=pi.guid).count() == a)

    def test_every_row_carries_its_PROVENANCE(self, client, db):
        """So the projection never has to be trusted on its own."""
        pi, res = _patient(db)
        res.resource_json = {"resourceType": "Patient", "id": res.resource_id,
                             "address": [{"city": "Gamlestad"}]}
        db.session.flush()
        ps.rebuild_for_patient(pi.guid)
        db.session.commit()
        for f in _db.session.query(PatientStateFact).filter_by(patient_guid=pi.guid):
            assert f.source_table in ("fhir_resources", "patient_clinic_assignments")
            assert f.source_guid is not None
