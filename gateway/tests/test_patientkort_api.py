"""GET /api/v1/patients/<guid>/patientkort — the shared card's view-model for
dashboard.pdhc and record.pdhc.

Gated EXACTLY as /euips-summary (the shared `_summary_reader_patient`), audited,
spärr detail redacted as GET .../blocks redacts it, and the JSON must render
the same card as eps's own patient page. AUTH ON with real keys for the gate
tests -- under AUTH_DISABLED the gate does not run. Synthetic data only.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.user import User
from app.services import fhir_service
from app.services.auth_service import hash_api_key
from app.services.personnummer import build_synthetic

PNR = build_synthetic("1958-04-11")
BLOCK_SETTER = uuid.uuid4()      # who set the block: must not reach clinic A


def _url(guid):
    return f"/api/v1/patients/{guid}/patientkort"


@pytest.fixture
def world(client, db):
    org = str(uuid.uuid4())
    unit_a = Clinic(name="VC Kortby", organisation_guid=str(uuid.uuid4()),
                    care_organisation_guid=org)
    unit_b = Clinic(name="Mottagning B", organisation_guid=str(uuid.uuid4()),
                    care_organisation_guid=org)
    unit_c = Clinic(name="Annan enhet", organisation_guid=str(uuid.uuid4()))
    vg = Clinic(name="Region Kort", organisation_guid=org, care_organisation_guid=org)
    db.session.add_all([unit_a, unit_b, unit_c, vg]); db.session.flush()

    pid = str(uuid.uuid4())
    pres = fhir_service.create_resource("Patient", {"resourceType": "Patient", "id": pid})
    db.session.flush()
    p = db.session.query(PatientIndex).filter_by(resource_id=pid).first()
    if p is None:
        p = PatientIndex(fhir_resource_guid=pres.guid, resource_id=pid)
        db.session.add(p)
    p.family_name, p.given_name = "Apisson", "Asta"
    p.birth_date, p.gender, p.identifier_value = date(1958, 4, 11), "female", PNR
    db.session.flush()
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=unit_a.guid))
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=unit_b.guid))
    fhir_service.create_resource("Condition", {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003",
                             "display": "Hypertoni"}]}}, patient_guid=p.guid)
    # A block on unit B's data, set by someone a unit-A reader may not learn.
    db.session.add(PatientBlock(patient_guid=p.guid, source_scope_type="clinic",
                                source_scope_id=unit_b.guid, created_reason="test",
                                created_by_user_guid=BLOCK_SETTER))
    db.session.commit()
    return {"p": p, "a": unit_a, "b": unit_b, "c": unit_c}


def _reader(db, clinic=None, *, su=False):
    """A real eps user with a real ApiKey -> `Authorization: ApiKey ...`."""
    tag = uuid.uuid4().hex[:8]
    u = User(username=f"pk{tag}@x.test", email=f"pk{tag}@x.test",
             display_name=f"pk {tag}", is_superuser=su, is_active=True)
    db.session.add(u); db.session.flush()
    if clinic is not None:
        db.session.add(UserClinicAssignment(user_guid=u.guid, clinic_guid=clinic.guid))
    raw = f"kpk-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="pk", prefix=raw[:8],
                          scopes=[], is_active=True, user_guid=u.guid))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


@pytest.fixture
def auth_on(client):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
        yield client


# ── the gate ────────────────────────────────────────────────────────────


def test_allowed_reader_gets_the_card(auth_on, db, world):
    r = auth_on.get(_url(world["p"].guid), headers=_reader(db, world["a"]))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["version"] == 1
    pk = body["patientkort"]
    assert pk["name"] == "Apisson, Asta"
    assert pk["ids"]["guid"] == str(world["p"].guid)
    assert [d["display"] for d in pk["diagnoses"]] == ["Hypertoni"]
    assert {u["name"] for u in pk["units"]} == {"VC Kortby", "Mottagning B"}


def test_no_credential_is_401(auth_on, db, world):
    assert auth_on.get(_url(world["p"].guid)).status_code == 401
    assert auth_on.get(_url(world["p"].guid),
                       headers={"Authorization": "ApiKey junk"}).status_code == 401


def test_out_of_scope_reader_gets_the_SAME_404_as_a_missing_patient(auth_on, db, world):
    h = _reader(db, world["c"])
    hidden = auth_on.get(_url(world["p"].guid), headers=h)
    missing = auth_on.get(_url(uuid.uuid4()), headers=h)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.get_json() == missing.get_json()
    assert "Apisson" not in hidden.get_data(as_text=True)


def test_a_reader_with_no_unit_at_all_is_refused(auth_on, db, world):
    assert auth_on.get(_url(world["p"].guid), headers=_reader(db)).status_code == 404


def test_malformed_guid_is_400(auth_on, db, world):
    assert auth_on.get(_url("not-a-guid"), headers=_reader(db, world["a"])).status_code == 400


def test_the_card_and_the_summary_answer_the_SAME_for_every_reader(auth_on, db, world):
    """The card carries the summary; it must not be a looser door to it."""
    for h in ({}, _reader(db, world["a"]), _reader(db, world["c"]), _reader(db),
              _reader(db, su=True)):
        card = auth_on.get(_url(world["p"].guid), headers=h).status_code
        summ = auth_on.get(f"/api/v1/patients/{world['p'].guid}/euips-summary",
                           headers=h).status_code
        assert card == summ, (h, card, summ)


def test_a_FAILING_scope_check_is_503_not_not_found(client, db, world, monkeypatch):
    from app.services import patient_export as px

    def boom(guids):
        raise RuntimeError("scope store unreachable")
    monkeypatch.setattr(px, "exportable", boom)
    r = client.get(_url(world["p"].guid))
    assert r.status_code == 503 and r.get_json()["error"] == "scope_undetermined"


def test_the_read_is_AUDITED(auth_on, db, world):
    auth_on.get(_url(world["p"].guid), headers=_reader(db, world["a"]))
    rows = db.session.query(AuditLog).filter_by(event_type="patientkort_read").all()
    assert rows and str(rows[-1].patient_guid) == str(world["p"].guid)


# ── spärr ───────────────────────────────────────────────────────────────


def test_block_banner_shown_but_WHO_set_it_withheld_outside_its_scope(auth_on, db, world):
    text = auth_on.get(_url(world["p"].guid), headers=_reader(db, world["a"])).get_data(as_text=True)
    pk = json.loads(text)["patientkort"]
    assert any(b["kind"] == "block" for b in pk["banners"]), "PDL ¶3 notice must show"
    assert str(BLOCK_SETTER) not in text and str(BLOCK_SETTER)[:8] not in text
    assert "Mottagning B" not in json.dumps(
        next(b for b in pk["banners"] if b["kind"] == "block")["prov"])


def test_block_setter_visible_inside_its_scope_and_to_SU(auth_on, db, world):
    """Control for the test above: the redaction is what hides it, not absence."""
    for h in (_reader(db, world["b"]), _reader(db, su=True)):
        text = auth_on.get(_url(world["p"].guid), headers=h).get_data(as_text=True)
        assert str(BLOCK_SETTER)[:8] in text


# ── the contract: JSON-safe, and it renders the admin page's card ───────


def test_pk_is_json_safe_and_round_trips(client, db, world):
    from app.admin import _patientkort
    pk = _patientkort(world["p"])
    assert json.loads(json.dumps(pk)) == pk


def _card_html(page: str) -> str:
    m = re.search(r'<section class="pk".*?</script>', page, re.S)
    assert m, "no card on the page"
    return m.group(0)


def test_the_JSON_renders_the_SAME_card_as_the_admin_page(client, db, world, app):
    from flask import render_template
    page = client.get(f"/admin/patients/{world['p'].guid}").get_data(as_text=True)
    pk = client.get(_url(world["p"].guid)).get_json()["patientkort"]
    with app.test_request_context():
        from_json = render_template("_patientkort.html", pk=pk)
    assert _card_html(from_json) == _card_html(page)
    assert "Hypertoni" in from_json and "Spärr aktiv" in from_json
    assert from_json.count(PNR) == 1      # the field, never a pop-out
