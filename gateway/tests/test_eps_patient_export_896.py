"""#896 (EPS B7) — export selected patients as CSV and as a FHIR Bundle.

Nothing like this existed: measured across ips, cdr and cdr_6, there was no
`/export` route and no CSV writer anywhere. So the access and audit properties
are built rather than inherited, and these tests are mostly about them.

The two that matter most are the ones that would let data out:

  - `TestScope` — a patient the reader may not open individually must be
    ABSENT from an export of fifty, and absent rather than refused, because a
    refusal confirms the guid exists.
  - `TestTheSetFilterAgreesWithThePerPatientGate` — an export is a SECOND
    consumer of "may this reader see this patient", and two consumers with
    different answers is exactly what `care_access_policy`'s "no two consumers
    may enforce different zone rules" exists to prevent.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db as _db
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.user import User
from app.services import patient_export as px
from app.services import patient_state

#: Checksum DELIBERATELY invalid, like the other fixtures in this suite: this
#: repo is public and a valid personnummer could belong to a real person (#405
#: confinement). Do not "correct" it. It is here because the CSV must be proven
#: NOT to carry it.
PNR = "197001011234"


def _patient(db, family, *, clinic=None, ended=None, pnr=PNR):
    rid = str(uuid.uuid4())
    res = FhirResource(
        resource_type="Patient", resource_id=rid,
        resource_json={"resourceType": "Patient", "id": rid,
                       "name": [{"family": family, "given": ["Test"]}],
                       "address": [{"use": "home", "city": "Gamlestad",
                                    "country": "SE"}],
                       "identifier": [{"value": pnr}]})
    db.session.add(res)
    db.session.flush()
    pi = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                      family_name=family, given_name="Test",
                      identifier_value=pnr)
    db.session.add(pi)
    db.session.flush()
    res.patient_guid = pi.guid
    if clinic is not None:
        db.session.add(PatientClinicAssignment(
            patient_guid=pi.guid, clinic_guid=clinic.guid, ended_at=ended))
    db.session.flush()
    patient_state.rebuild_for_patient(pi.guid)
    db.session.commit()
    return pi


def _clinic(db, name):
    c = Clinic(name=name, organisation_guid=str(uuid.uuid4()), is_active=True)
    db.session.add(c)
    db.session.flush()
    return c


def _staff(db, label, clinic):
    u = User(username=label, email=f"{label}@x.test", display_name=label,
             is_active=True, is_superuser=False)
    _db.session.add(u)
    _db.session.flush()
    _db.session.add(UserClinicAssignment(user_guid=u.guid,
                                         clinic_guid=clinic.guid))
    _db.session.commit()
    return u


@pytest.fixture
def admin_user(db):
    u = User(username="admin896", email="a896@x.test", display_name="Admin",
             is_active=True, is_superuser=True)
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture
def acting(app):
    """Act as `user` inside a request context.

    `patient_export` reads `g.current_user` and `session["sso_user"]` — the
    two things the real request paths set — so the tests push a request
    context and set the first. Calling the service with neither is what the
    gate is FOR, and `test_a_reader_with_NO_clinic_is_refused_outright`
    exercises that on purpose.
    """
    @contextmanager
    def _acting(user):
        with app.test_request_context("/api/v1/patients/export", method="POST"):
            from flask import g as _g
            _g.current_user = user
            yield
    return _acting


class TestCsv:
    def test_an_admin_exports_the_selection(self, client, db, acting, admin_user):
        a = _patient(db, "Alfasson")
        with acting(admin_user):
            out = px.export([str(a.guid)], fmt="csv")
        assert out["exported"] == 1
        head, *rows = out["body"].strip().split("\n")
        assert head.split(",") == px.CSV_AS_AT_COLUMNS
        assert any("Gamlestad" in r for r in rows), rows

    def test_the_CSV_carries_NO_personnummer(self, client, db, acting, admin_user):
        """A CSV leaves the system, `personnummer` is under a hard confinement
        rule (#405) and no masking helper exists in this repo. The export keys
        on guid instead. The FHIR Bundle is the deliberate exception."""
        a = _patient(db, "Numsson")
        with acting(admin_user):
            body = px.export([str(a.guid)], fmt="csv")["body"]
        assert PNR not in body, "personnummer reached the CSV"

    def test_no_column_is_called_date(self, client, db):
        """A single `date` column would re-introduce exactly the conflation
        #895 exists to remove."""
        for cols in (px.CSV_AS_AT_COLUMNS, px.CSV_HISTORY_COLUMNS):
            assert "date" not in cols, cols

    def test_history_mode_carries_BOTH_axes_and_as_at_does_not(self, client, db, acting, admin_user):
        a = _patient(db, "Historiesson")
        with acting(admin_user):
            h = px.export([str(a.guid)], fmt="csv", mode="history")["body"]
            n = px.export([str(a.guid)], fmt="csv", mode="as_at")["body"]
        assert "recorded_at" in h.split("\n")[0]
        assert "recorded_until" in h.split("\n")[0]
        assert "recorded_at" not in n.split("\n")[0]

    def test_an_unknown_mode_is_refused_by_name(self, client, db, acting, admin_user):
        a = _patient(db, "Lagesson")
        with acting(admin_user), pytest.raises(ValueError):
            px.export([str(a.guid)], fmt="csv", mode="sometime")


class TestScope:
    def test_a_patient_at_ANOTHER_clinic_is_ABSENT_not_refused(self, client, db, acting):
        """Absent, so the export leaks no existence either — the same
        reasoning as onboard's flat 404 on a bad invite token."""
        mine, theirs = _clinic(db, "Mine"), _clinic(db, "Theirs")
        a = _patient(db, "Minsson", clinic=mine)
        b = _patient(db, "Deirassons", clinic=theirs)
        staff = _staff(db, "staff896", mine)
        with acting(staff):
            out = px.export([str(a.guid), str(b.guid)], fmt="csv")
        assert out["exported"] == 1
        assert out["withheld"] == 1
        # The ALLOWED patient's data is there — otherwise "withheld the other
        # one" would also pass for an export that produced nothing at all.
        assert "Minsson" in out["body"]
        # The WITHHELD patient appears by neither name nor guid.
        assert "Deirassons" not in out["body"]
        assert str(b.guid) not in out["body"]

    def test_an_ENDED_assignment_withholds_the_patient(self, client, db, acting):
        """#899(b) again: a reader at a clinic the patient has LEFT is not a
        reader of that patient."""
        mine = _clinic(db, "Mine2")
        gone = _patient(db, "Lamnadsson", clinic=mine,
                        ended=datetime(2026, 1, 1, tzinfo=timezone.utc))
        staff = _staff(db, "staff896b", mine)
        with acting(staff):
            out = px.export([str(gone.guid)], fmt="csv")
        assert out["exported"] == 0 and out["withheld"] == 1

    def test_an_ADMIN_sees_every_requested_patient(self, client, db, acting, admin_user):
        """The control on the two above: the narrowing is the reader's scope,
        not a blanket refusal."""
        c = _clinic(db, "Any")
        a = _patient(db, "Adminsson", clinic=c)
        b = _patient(db, "Ocksasson")
        with acting(admin_user):
            out = px.export([str(a.guid), str(b.guid)], fmt="csv")
        assert out["exported"] == 2 and out["withheld"] == 0

    def test_a_reader_with_NO_clinic_is_refused_outright(self, client, db, acting):
        """Distinct from exporting nothing: no scope at all is a permission
        answer, and it fails closed."""
        c = _clinic(db, "Elsewhere")
        a = _patient(db, "Ingensson", clinic=c)
        lonely = User(username="lonely896", email="l@x.test",
                      display_name="L", is_active=True, is_superuser=False)
        _db.session.add(lonely)
        _db.session.commit()
        with acting(lonely):
            with pytest.raises(px.ExportNotPermitted):
                px.export([str(a.guid)], fmt="csv")


class TestTheSetFilterAgreesWithThePerPatientGate:
    def test_they_agree_on_every_candidate(self, client, db, acting):
        """An export is a SECOND consumer of "may this reader see this
        patient". Two consumers with different answers is what
        care_access_policy's "no two consumers may enforce different zone
        rules" exists to prevent, so the two are compared directly."""
        from app.api.blocks_routes import _can_act_on_patient
        mine, theirs = _clinic(db, "A"), _clinic(db, "B")
        here = _patient(db, "Harsson", clinic=mine)
        there = _patient(db, "Darsson", clinic=theirs)
        ended = _patient(db, "Slutsson", clinic=mine,
                         ended=datetime(2026, 1, 1, tzinfo=timezone.utc))
        orphan = _patient(db, "Utansson")
        staff = _staff(db, "staff896c", mine)
        cands = [here, there, ended, orphan]

        with acting(staff):
            allowed, _ = px.exportable([str(p.guid) for p in cands])
            for p in cands:
                per_patient = _can_act_on_patient(p.guid)
                in_set = str(p.guid) in allowed
                assert per_patient == in_set, (
                    f"{p.family_name}: per-patient={per_patient} set={in_set}")


class TestAudit:
    def test_one_row_per_patient_not_one_per_batch(self, client, db, acting, admin_user):
        """A single "exported a batch" row makes the log useless for the only
        question anyone asks of it: who has seen this patient's data?"""
        a = _patient(db, "Ensson")
        b = _patient(db, "Tvasson")
        before = db.session.query(AuditLog).filter_by(
            event_type="patient.exported").count()
        with acting(admin_user):
            px.export([str(a.guid), str(b.guid)], fmt="csv")
        db.session.commit()
        rows = (db.session.query(AuditLog)
                .filter_by(event_type="patient.exported").all())
        assert len(rows) - before == 2, len(rows)
        assert {str(r.patient_guid) for r in rows} >= {str(a.guid), str(b.guid)}

    def test_a_WITHHELD_patient_is_not_audited(self, client, db, acting):
        """Nothing is audited that was not rendered — an audit row saying a
        patient was exported when they were not is worse than none."""
        mine, theirs = _clinic(db, "M"), _clinic(db, "T")
        a = _patient(db, "Jasson", clinic=mine)
        b = _patient(db, "Nejsson", clinic=theirs)
        staff = _staff(db, "staff896d", mine)
        with acting(staff):
            px.export([str(a.guid), str(b.guid)], fmt="csv")
        _db.session.commit()
        audited = {str(r.patient_guid) for r in _db.session.query(AuditLog)
                   .filter_by(event_type="patient.exported").all()}
        assert str(a.guid) in audited
        assert str(b.guid) not in audited


class TestLimits:
    def test_past_the_cap_is_refused_BY_NAME(self, client, db, acting, admin_user):
        """Not a timeout and not a 500. A permanent condition reported as
        transient tells the caller to retry forever (#833)."""
        with acting(admin_user), pytest.raises(px.ExportTooLarge) as e:
            px.export([str(uuid.uuid4()) for _ in range(px.MAX_PATIENTS + 1)],
                      fmt="csv")
        assert str(px.MAX_PATIENTS) in str(e.value)

    def test_exactly_the_cap_is_allowed(self, client, db, acting, admin_user):
        """The boundary, so the cap is off-by-one-proof."""
        guids = [str(uuid.uuid4()) for _ in range(px.MAX_PATIENTS)]
        with acting(admin_user):
            out = px.export(guids, fmt="csv")   # none exist, nothing exported
        assert out["exported"] == 0

    def test_an_empty_selection_is_refused(self, client, db, acting, admin_user):
        with acting(admin_user), pytest.raises(ValueError):
            px.export([], fmt="csv")


class TestFhirBundle:
    def test_it_is_a_collection_with_the_patients_resources(self, client, db, acting, admin_user):
        a = _patient(db, "Bundelsson")
        with acting(admin_user):
            b = px.export([str(a.guid)], fmt="fhir")["body"]
        assert b["resourceType"] == "Bundle"
        assert b["type"] == "collection"
        assert b["total"] >= 1
        assert any(e["resource"]["resourceType"] == "Patient"
                   for e in b["entry"])

    def test_it_says_IN_THE_DOCUMENT_that_it_is_not_EPS_conformant(self, client, db, acting, admin_user):
        """A recipient must not have to read a docstring to learn this. EPS is
        R4, this is R5 (#877), and CODES_VERIFIED is still False."""
        a = _patient(db, "Taggsson")
        with acting(admin_user):
            b = px.export([str(a.guid)], fmt="fhir")["body"]
        tag = b["meta"]["tag"][0]
        assert tag["code"] == "not-eps-conformant"
        assert "R5" in tag["display"] and "R4" in tag["display"]

    def test_the_FHIR_bundle_DOES_carry_the_identifier(self, client, db, acting, admin_user):
        """The deliberate exception to the CSV rule: `Patient.identifier` is
        part of the document by design."""
        a = _patient(db, "Idsson")
        with acting(admin_user):
            b = px.export([str(a.guid)], fmt="fhir")["body"]
        assert PNR in str(b)

    def test_asking_for_R4_is_refused_BY_NAME(self, client, db):
        """#897: the version is a parameter so adding R4 later is additive
        rather than a refactor, and anything else is refused instead of being
        quietly answered in R5."""
        a = _patient(db, "Fyrasson")
        with pytest.raises(px.UnsupportedFhirVersion) as e:
            px.to_fhir_bundle([str(a.guid)], version="R4")
        assert "R5" in str(e.value)


class TestTheRoute:
    def test_it_returns_a_csv_attachment(self, client, db):
        a = _patient(db, "Routesson")
        r = client.post("/api/v1/patients/export",
                        json={"patient_guids": [str(a.guid)], "format": "csv"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.headers["Content-Type"].startswith("text/csv")
        assert "attachment" in r.headers["Content-Disposition"]
        assert r.headers["X-Export-Exported"] == "1"

    def test_past_the_cap_is_413_with_a_code(self, client, db):
        r = client.post("/api/v1/patients/export",
                        json={"patient_guids":
                              [str(uuid.uuid4())
                               for _ in range(px.MAX_PATIENTS + 1)],
                              "format": "csv"})
        assert r.status_code == 413
        assert r.get_json()["code"] == "export_too_large"

    def test_a_bad_as_at_is_400_not_500(self, client, db):
        a = _patient(db, "Datumsson")
        r = client.post("/api/v1/patients/export",
                        json={"patient_guids": [str(a.guid)],
                              "format": "csv", "as_at": "yesterday"})
        assert r.status_code == 400
