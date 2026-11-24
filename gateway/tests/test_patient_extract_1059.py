"""#1059 (record.pdhc stage 6b): eps's part of the patient extract.

    GET /api/v1/patient-extract/<patient_guid>

AUTH ON throughout; only the outbound sso call (`httpx.get`) is patched, as in
test_invite_reads_bearer_1050 / test_patient_access_log_1045. The only
personnummer is the synthetic Tolvan Tolvansson 19121212-1212.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import Column, ForeignKey, MetaData, String, Table

from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.emergency_access import EmergencyAccess
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.patient_block import PatientBlock
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.patient_proxy_grant import PatientProxyGrant
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.base import db as _db
from app.services import patient_extract as ex
from app.services.cdr_patient_reported_derivation import ENDORSED_TAG, ENDORSEMENT_EXT
from app.services.personnummer import PERSONNUMMER_SYSTEM
from tests import test_invite_reads_bearer_1050 as base
from tests.test_invite_reads_bearer_1050 import (  # noqa: F401 — fixtures
    H, NOBODY, UNIT_A, UNIT_B, _key, world)

PNR = "19121212-1212"
SECRET = "push-secret-1059-must-not-leak"
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


class FakeSso(base.FakeSso):
    def __init__(self):
        super().__init__()
        extra = {"doctor_a": (UNIT_A, "doctor"), "other_a": (UNIT_A, "other_care"),
                 "researcher_a": (UNIT_A, "researcher"), "nurse_b": (UNIT_B, "nurse")}
        for kind, (unit, role) in extra.items():
            b = base._blob(kind)
            b["affiliations"] = [{"care_unit_guid": unit, "role": role}]
            self.blobs[kind] = b


@pytest.fixture
def api(client):
    cfg = {"AUTH_DISABLED": False, "OAUTH_BASE_URL": base.SSO,
           "SSO_CLIENT_ID": "eps-test", "SSO_CLIENT_SECRET": "eps-test-secret"}
    with patch.dict(client.application.config, cfg), \
            patch("app.services.auth_service.httpx.get", FakeSso()):
        yield client


def X(g):
    return f"/api/v1/patient-extract/{g}"


def _fr(db, rtype, rid, version, rj, patient_guid, status="active", at=T0):
    r = FhirResource(resource_type=rtype, resource_id=rid, version_id=version,
                     resource_json=rj, patient_guid=patient_guid, status=status,
                     created_at=at)
    db.session.add(r)
    db.session.flush()
    return r


@pytest.fixture
def full(db, world):
    """Patient pa with something in every table the extract covers."""
    pa = db.session.get(PatientIndex, uuid.UUID(world["pa"]))
    pid = pa.guid
    rid = pa.resource_id
    v1 = db.session.query(FhirResource).filter_by(resource_type="Patient", resource_id=rid).one()
    ident = [{"system": PERSONNUMMER_SYSTEM, "value": PNR}]
    v1.resource_json = {"resourceType": "Patient", "id": rid, "identifier": ident,
                        "name": [{"family": "Tolvansson", "given": ["Tolvan"]}],
                        "birthDate": "1912-12-12", "gender": "male",
                        "address": [{"line": ["Gamla gatan 1"], "city": "Lund"}],
                        "contact": [{"name": {"text": "Anna Tolvansson"},
                                     "relationship": [{"text": "dotter"}]}]}
    v1.status = "superseded"
    _fr(db, "Patient", rid, 2, {**v1.resource_json,
                                "address": [{"line": ["Nya gatan 2"], "city": "Malmö"}],
                                "telecom": [{"system": "phone", "value": "070-0000000"}]},
        pid, at=T0 + timedelta(days=1))
    # a relative with their own (synthetic) personnummer-system identifier
    _fr(db, "RelatedPerson", "rp-1", 1, {"resourceType": "RelatedPerson", "id": "rp-1",
                                         "identifier": [{"system": PERSONNUMMER_SYSTEM, "value": PNR}],
                                         "name": [{"text": "Anna Tolvansson"}]}, pid)
    # a CDR-backed condition in two versions, one EPS-only observation
    cond = {"resourceType": "Condition", "id": "c-1",
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "49436004",
                                 "display": "Förmaksflimmer"}]},
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "onsetDateTime": "2020-01-01",
            "subject": {"reference": f"Patient/{pid}",
                        "identifier": {"system": PERSONNUMMER_SYSTEM, "value": PNR}},
            "identifier": [{"system": "https://cdr.pdhc.se/fhir/Condition", "value": "cdr-guid-1",
                            "assigner": {"display": "cdr1"}}]}
    _fr(db, "Condition", "c-1", 1, cond, pid, status="superseded")
    _fr(db, "Condition", "c-1", 2, {**cond, "clinicalStatus": {"coding": [{"code": "resolved"}]}},
        pid, at=T0 + timedelta(days=3))
    _fr(db, "Observation", "o-1", 1, {"resourceType": "Observation", "id": "o-1",
                                      "code": {"text": "Vikt"}, "effectiveDateTime": "2026-10-01",
                                      "valueQuantity": {"value": 70, "unit": "kg"}}, pid)
    # a patient-card entry: endorsed in version 1, retired by a newer card
    card = {"resourceType": "AllergyIntolerance", "id": "a-1",
            "meta": {"tag": [dict(ENDORSED_TAG)]}, "code": {"text": "Jordnötter"},
            "extension": [{"url": ENDORSEMENT_EXT, "extension": [
                {"url": "informant", "valueReference": {"reference": f"Patient/{pid}"}},
                {"url": "cardVersion", "valueString": "v-2026-11-01"},
                {"url": "endorsedBy", "extension": [
                    {"url": "who", "valueReference": {"display": "Syster Sara",
                                                      "identifier": {"value": "u-1"}}},
                    {"url": "at", "valueDateTime": "2026-11-02T10:00:00Z"}]}]}]}
    _fr(db, "AllergyIntolerance", "a-1", 1, card, pid, status="superseded")
    _fr(db, "AllergyIntolerance", "a-1", 2, card, pid, status="retired")
    clinic_a = db.session.query(Clinic).filter_by(organisation_guid=UNIT_A).one()
    clinic_b = db.session.query(Clinic).filter_by(organisation_guid=UNIT_B).one()
    db.session.add(PatientClinicAssignment(patient_guid=pid, clinic_guid=clinic_b.guid,
                                           assigned_at=T0 - timedelta(days=30),
                                           ended_at=T0 - timedelta(days=5)))
    db.session.add(PatientBlock(patient_guid=pid, source_scope_id=clinic_b.guid,
                                created_reason="vill inte", lifted_at=T0,
                                lift_kind="consent", lifted_reason="ångrade sig"))
    db.session.add(PatientBlock(patient_guid=pid, source_scope_id=uuid.uuid4()))
    db.session.add(PatientConsent(patient_guid=pid, grantee_caregiver_guid=uuid.uuid4(),
                                  contract_guid=uuid.uuid4(), granted_via="contract",
                                  revoked_at=T0, revoked_reason="avtal slut"))
    db.session.add(EmergencyAccess(patient_guid=pid, reader_care_unit_guid=uuid.uuid4(),
                                   reason="medvetslös", actor_label="Dr Akut",
                                   expires_at=T0 + timedelta(days=1),
                                   session_id="sid-1059-must-not-leak"))
    db.session.add(PatientProxyGrant(patient_guid=pid, proxy_user_guid=uuid.uuid4(),
                                     proxy_label="min dotter Anna"))
    ic = IpsCard(patient_guid=pid, title="Resa")
    db.session.add(ic)
    db.session.flush()
    bundle = {"resourceType": "Bundle", "entry": [{"resource": {
        "resourceType": "Patient", "identifier": [{"system": PERSONNUMMER_SYSTEM, "value": PNR}]}}]}
    s1 = IpsSnapshot(card_guid=ic.guid, bundle_json=bundle, composition_date=T0, mode="full",
                     created_at=T0)
    s2 = IpsSnapshot(card_guid=ic.guid, bundle_json=bundle, composition_date=T0, mode="full",
                     created_at=T0 + timedelta(days=1))
    db.session.add_all([s1, s2, IpsCard(patient_guid=pid, title="Tomt kort")])
    dest = PushDestination(name="Mottagare X", destination_type="fhir",
                           endpoint_url=f"https://x.test/?token={SECRET}",
                           auth_config={"secret": SECRET}, headers={"X-Key": SECRET})
    db.session.add(dest)
    db.session.flush()
    db.session.add(PushJob(snapshot_guid=s1.guid, destination_guid=dest.guid, status="failed",
                           error_message=f"POST https://x.test/?token={SECRET} 500"))
    db.session.commit()
    _ = clinic_a
    return world


def _sec(body, key):
    return next(s for s in body["sections"] if s["key"] == key)


def _extract_events(db, patient, outcome=None):
    rows = db.session.query(AuditLog).filter_by(event_type="patient_extract").all()
    rows = [r for r in rows if str(r.patient_guid) == patient]
    return [r for r in rows if outcome is None or r.detail.get("outcome") == outcome]


# ------------------------------------------------------------------ the gate

def test_affiliated_nurse_gets_the_extract(api, db, full):
    r = api.get(X(full["pa"]), headers=H("pro_a"))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["schema"] == "pdhc.patient-extract/1" and body["service"] == "eps.pdhc"
    assert body["patient_guid"] == full["pa"] and body["complete"] is True
    assert [s["key"] for s in body["sections"]] == [
        "identity", "care_units", "contacts", "related_persons", "proxy_grants", "blocks",
        "consents", "emergency_access", "patient_card", "conditions", "summary",
        "eps_documents", "eps_deliveries"]


def test_affiliated_doctor_and_su_get_it(api, db, full):
    assert api.get(X(full["pa"]), headers=H("doctor_a")).status_code == 200
    assert api.get(X(full["pb"]), headers=H("su")).status_code == 200


def test_d9_other_roles_at_the_unit_are_the_same_404_as_nobody(api, db, full):
    nobody = api.get(X(NOBODY), headers=H("pro_a"))
    for kind in ("other_a", "researcher_a"):
        r = api.get(X(full["pa"]), headers=H(kind))
        assert r.status_code == nobody.status_code == 404
        assert r.get_json() == nobody.get_json()


def test_other_unit_ended_listing_and_inactive_unit_are_404(api, db, full):
    # pa was listed at B but that listing ENDED: a nurse at B is out of scope
    assert api.get(X(full["pa"]), headers=H("nurse_b")).status_code == 404
    assert api.get(X(full["pb"]), headers=H("pro_a")).status_code == 404
    assert api.get(X(full["pg"]), headers=H("pro_gone")).status_code == 404
    assert api.get(X(full["pa"]), headers=H("legacy_member")).status_code == 404


def test_a_service_key_is_refused_by_name_and_logged(api, db, full):
    r = api.get(X(full["pa"]), headers=_key(db))
    assert r.status_code == 403 and r.get_json()["error"] == "bearer_required"
    ev = _extract_events(db, full["pa"], "denied")
    assert [e.detail["reason"] for e in ev] == ["bearer_required"]


def test_patient_bearer_unknown_token_and_must_change_are_refused(api, db, full):
    assert api.get(X(full["pa"]), headers=H("patient")).status_code == 401
    assert api.get(X(full["pa"]), headers=H("nobody")).status_code == 401
    assert api.get(X(full["pa"]), headers=H("must_change")).status_code in (401, 403)


def test_malformed_guid_is_400(api, db, full):
    assert api.get(X("inte-en-guid"), headers=H("su")).status_code == 400


def test_every_call_is_audited_with_its_outcome(api, db, full):
    api.get(X(full["pa"]), headers=H("pro_a"))
    api.get(X(full["pb"]), headers=H("pro_a"))
    api.get(X(NOBODY), headers=H("pro_a"))
    served = _extract_events(db, full["pa"], "served")
    assert len(served) == 1 and served[0].actor_type == "user"
    assert served[0].detail["n_items"] > 0
    assert [e.detail["reason"] for e in _extract_events(db, full["pb"], "denied")] == ["out_of_scope"]
    assert len(_extract_events(db, NOBODY, "not_found")) == 1


def test_the_audit_row_reaches_the_loggkontroll_view_as_denied(api, db, full):
    api.get(X(full["pb"]), headers=H("pro_a"))
    r = api.get(f"/api/v1/audit/patients/{full['pb']}", headers=H("su"))
    items = [i for i in r.get_json()["items"] if i["action"] == "patient_extract"]
    assert [i["outcome"] for i in items] == ["denied"]


# ------------------------------------------------------------------- content

@pytest.fixture
def body(api, full):
    r = api.get(X(full["pa"]), headers=H("su"))
    assert r.status_code == 200
    return r.get_json()


def test_counts_match_the_database(body, db, full):
    pid = uuid.UUID(full["pa"])
    distinct = {(r.resource_type, r.resource_id): r for r in
                db.session.query(FhirResource).filter(FhirResource.patient_guid == pid)}
    fhir_count = len(distinct) + (0 if ("Patient", full["pa_rid"]) in distinct else 1)
    expected = {
        "care_units": db.session.query(PatientClinicAssignment).filter_by(patient_guid=pid).count(),
        "blocks": db.session.query(PatientBlock).filter_by(patient_guid=pid).count(),
        "consents": db.session.query(PatientConsent).filter_by(patient_guid=pid).count(),
        "emergency_access": db.session.query(EmergencyAccess).filter_by(patient_guid=pid).count(),
        "proxy_grants": db.session.query(PatientProxyGrant).filter_by(patient_guid=pid).count(),
        "eps_documents": db.session.query(IpsCard).filter_by(patient_guid=pid).count(),
        "eps_deliveries": db.session.query(PushJob).join(IpsSnapshot).join(IpsCard)
        .filter(IpsCard.patient_guid == pid).count(),
    }
    for key, n in expected.items():
        assert _sec(body, key)["count"] == n > 0, key
    fhir_sections = ("related_persons", "patient_card", "conditions", "summary")
    assert sum(_sec(body, k)["count"] for k in fhir_sections) + 1 == fhir_count
    # every version row of the patient's FHIR data is in the extract once
    versions = sum(len(i["versions"]) for k in fhir_sections + ("identity",)
                   for i in _sec(body, k)["items"] if i["resource_type"] != "PatientIndex")
    rows = db.session.query(FhirResource).filter(_db.or_(
        FhirResource.patient_guid == pid,
        _db.and_(FhirResource.resource_type == "Patient",
                 FhirResource.resource_id == full["pa_rid"]))).count()
    assert versions == rows == 8   # Patient 2, RelatedPerson 1, Condition 2, Observation 1, card 2


def test_identity_has_every_patient_version_and_the_personnummer(body):
    sec = _sec(body, "identity")
    patient = next(i for i in sec["items"] if i["resource_type"] == "Patient")
    assert [v["version"] for v in patient["versions"]] == [1, 2]
    assert [v["status"] for v in patient["versions"]] == ["superseded", "active"]
    v2 = patient["versions"][1]
    assert PNR in v2["summary_sv"] and "Malmö" in v2["summary_sv"] and "070-0000000" in v2["summary_sv"]
    assert v2["event_time"] is None and v2["recorded_at"].startswith("2026-11-02")
    idx = next(i for i in sec["items"] if i["resource_type"] == "PatientIndex")
    assert "EHDS" in idx["versions"][0]["summary_sv"]


def test_personnummer_appears_only_in_identity(body):
    for s in body["sections"]:
        text = json.dumps(s, ensure_ascii=False)
        if s["key"] == "identity":
            assert PNR in text
        else:
            assert PNR not in text, s["key"]
    assert ex.REDACTED_PNR in json.dumps(_sec(body, "eps_documents"), ensure_ascii=False)


def test_no_secrets_session_ids_or_key_hashes(api, db, full):
    _key(db)
    text = api.get(X(full["pa"]), headers=H("su")).get_data(as_text=True)
    for leak in (SECRET, "sid-1059-must-not-leak", "key_hash", "auth_config"):
        assert leak not in text, leak


def test_care_units_include_ended_with_dates(body):
    items = _sec(body, "care_units")["items"]
    assert sorted(i["current_status"] for i in items) == ["active", "ended"]
    ended = next(i for i in items if i["current_status"] == "ended")
    assert ended["versions"][0]["row"]["ended_at"] and "till" in ended["versions"][0]["summary_sv"]
    assert ended["versions"][0]["recorded_at"] is None


def test_contacts_follow_patient_versions(body):
    (item,) = _sec(body, "contacts")["items"]
    assert len(item["versions"]) == 2 and "Anna Tolvansson (dotter)" in item["versions"][0]["summary_sv"]


def test_blocks_consents_proxies_carry_their_lifecycle(body):
    lifted = next(i for i in _sec(body, "blocks")["items"]
                  if any(e["event"] == "lifted" for e in i["events"]))
    assert "hävd" in lifted["versions"][0]["summary_sv"] and lifted["current_status"] == "inactive"
    (c,) = _sec(body, "consents")["items"]
    assert [e["event"] for e in c["events"]] == ["granted", "revoked"]
    assert "via contract" in c["versions"][0]["summary_sv"]
    (p,) = _sec(body, "proxy_grants")["items"]
    assert "min dotter Anna" in p["versions"][0]["summary_sv"]
    (e,) = _sec(body, "emergency_access")["items"]
    assert "medvetslös" in e["versions"][0]["summary_sv"]
    assert e["versions"][0]["recorded_at"] and e["versions"][0]["event_time"]


def test_conditions_carry_cdr_backing_and_both_versions(body):
    (c,) = _sec(body, "conditions")["items"]
    assert c["cdr_backed"] is True and c["cdr"] == {"name": "cdr1", "guid": "cdr-guid-1"}
    assert [v["status"] for v in c["versions"]] == ["superseded", "active"]
    assert c["versions"][0]["event_time"] == "2020-01-01"
    assert "förankrad i CDR (cdr1)" in c["versions"][1]["summary_sv"]
    (o,) = _sec(body, "summary")["items"]
    assert o["cdr_backed"] is False and "ej förankrad i CDR" in o["versions"][0]["summary_sv"]


def test_patient_card_has_all_versions_and_points_at_cdr1(body):
    sec = _sec(body, "patient_card")
    (a,) = sec["items"]
    assert [v["status"] for v in a["versions"]] == ["superseded", "retired"]
    v = a["versions"][0]
    assert v["card_version"] == "v-2026-11-01" and v["author"]["name"] == "Syster Sara"
    assert "godkänd av Syster Sara" in v["summary_sv"]
    assert sec["source_of_rest"] == "cdr1.pdhc" and "cdr1" in sec["note_sv"]


def test_eps_documents_list_every_snapshot(body):
    items = _sec(body, "eps_documents")["items"]
    by_title = {i["card"]["title"]: i for i in items}
    assert len(by_title["Resa"]["versions"]) == 2
    assert by_title["Tomt kort"]["versions"][0]["fhir"] is None
    (d,) = _sec(body, "eps_deliveries")["items"]
    assert d["versions"][0]["row"]["destination_name"] == "Mottagare X"


def test_an_empty_patient_gives_empty_sections_not_an_error(api, db, world):
    r = api.get(X(world["pa"]), headers=H("pro_a"))
    body = r.get_json()
    assert r.status_code == 200 and body["complete"] is True
    assert _sec(body, "blocks")["count"] == 0 and _sec(body, "care_units")["count"] == 1


# ------------------------------------------------------- coverage detector

def test_every_patient_linked_table_is_exported_or_excluded_by_name(app):
    with app.app_context():
        assert ex.uncovered_tables() == set()
        linked = ex.patient_linked_tables(_db.metadata.tables.values())
    assert set(ex.TABLE_COVERAGE) | set(ex.TABLE_EXCLUSIONS) == linked
    assert not set(ex.TABLE_COVERAGE) & set(ex.TABLE_EXCLUSIONS)
    assert all(len(r) > 40 for r in ex.TABLE_EXCLUSIONS.values())
    # positive control: the tables known to hold no patient data are not linked
    assert not linked & {"users", "clinics", "api_keys", "push_destinations",
                         "capability_statement", "host_usage", "user_clinic_assignments"}


def test_a_new_patient_table_is_detected(app):
    """CONTROL: a model with patient data added later and in neither map is
    reported — by column name, by FK to patient_index, and transitively."""
    m = MetaData()
    new = [Table("patient_notes_new", m, Column("id", String, primary_key=True),
                 Column("patient_guid", String)),
           Table("owner_link_new", m, Column("id", String, primary_key=True),
                 Column("owner", String, ForeignKey("patient_index.guid"))),
           Table("card_comment_new", m, Column("id", String, primary_key=True),
                 Column("card", String, ForeignKey("ips_snapshots.guid"))),
           Table("unrelated_new", m, Column("id", String, primary_key=True))]
    with app.app_context():
        tables = list(_db.metadata.tables.values()) + new
        assert ex.uncovered_tables(tables) == {
            "patient_notes_new", "owner_link_new", "card_comment_new"}
