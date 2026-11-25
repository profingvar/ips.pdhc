"""Patientkort: the shared patient card's view-model, its provenance pop-outs,
and the eps admin page that renders it. Synthetic data only."""
import re
import uuid
from datetime import date, datetime, timezone

import pytest

from app.services import patientkort_view as pk
from app.services.personnummer import build_synthetic

TODAY = date(2026, 11, 25)
PNR = build_synthetic("1961-09-23")


def _entry(rtype="Condition", rid=None, display="Typ 2-diabetes", code="44054006",
           status="active", cdr=None, **kw):
    e = {"resource_type": rtype, "resource_id": rid or str(uuid.uuid4()),
         "display": display, "code": code, "system": "http://snomed.info/sct",
         "status": status, "cdr_backed": cdr is not None, "cdr": cdr,
         "date": "2019-03-02", "onset": "2019-03-02", "provenance": None,
         "value": None, "unit": None}
    e.update(kw)
    return e


def _sections(**by_key):
    out = []
    for key, entries in by_key.items():
        if entries == "absent":
            out.append({"key": key, "status": pk.EXPLICITLY_ABSENT, "entries": [],
                        "absent": {"narrative_text": "Inga kända allergier"}})
        else:
            out.append({"key": key, "status": pk.PRESENT, "entries": entries, "absent": None})
    return out


def _patient(**kw):
    p = {"guid": str(uuid.uuid4()), "fhir_id": "pat-1", "family_name": "Jönsson",
         "given_name": "Hans", "birth_date": "1961-09-23", "gender": "male",
         "identifier_value": PNR, "is_active": True}
    p.update(kw)
    return p


def _all_pops(view):
    """Every pop-out dict in a built view."""
    pops = [view["name_prov"]] + [f["prov"] for f in view["fields"]]
    pops += [u["prov"] for u in view["units"]]
    pops += [b["prov"] for b in view["banners"] if b["prov"]]
    pops += [d["prov"] for d in view["diagnoses"]]
    pops += [e["prov"] for s in view["sections"] for e in s["entries"]]
    return pops


# ── formatting ──────────────────────────────────────────────────────────


class TestFormatting:
    @pytest.mark.parametrize("birth,expect", [
        ("1961-09-23", 65), ("1961-11-25", 65), ("1961-11-26", 64),
        (date(2000, 2, 29), 26), (None, None), ("2030-01-01", None), ("nonsense", None),
    ])
    def test_age(self, birth, expect):
        assert pk.age_years(birth, TODAY) == expect

    def test_name(self):
        assert pk.format_name("Jönsson", "Hans") == "Jönsson, Hans"
        assert pk.format_name(None, "Hans") == "—, Hans"
        assert pk.format_name("", "  ") == "Namn saknas"

    def test_personnummer_normalised_and_synthetic(self):
        short = PNR[2:].replace("-", "")
        out = pk.format_personnummer(short)
        assert out == {"text": PNR, "synthetic": True}
        assert pk.format_personnummer(None) == {"text": None, "synthetic": False}
        assert pk.format_personnummer("abc")["text"] == "abc"

    def test_sex_and_age_text(self):
        v = pk.build(_patient(gender="female"), today=TODAY)
        assert v["sex_text"] == "Kvinna" and v["age_text"] == "65 år"
        assert pk.build(_patient(gender=None, birth_date=None), today=TODAY)["age_text"] is None

    def test_dimensionless_unit_not_printed(self):
        assert pk._value_text({"value": 3, "unit": "1"}) == "3"
        assert pk._value_text({"value": 5.5, "unit": "mmol/L"}) == "5.5 mmol/L"


# ── diagnoses, sections, banners ────────────────────────────────────────


class TestCard:
    def test_cdr_backed_split_and_note(self):
        backed = _entry(cdr={"name": "cdr2", "guid": "g-1"})
        unbacked = _entry(display="Hypertoni", code="38341003")
        v = pk.build(_patient(), sections=_sections(problems=[backed, unbacked]), today=TODAY)
        by = {d["display"]: d for d in v["diagnoses"]}
        assert by["Typ 2-diabetes"]["cdr_backed"] and by["Typ 2-diabetes"]["cdr_name"] == "cdr2"
        assert by["Hypertoni"]["cdr_backed"] is False
        assert v["diagnosis_note"].startswith("1 av 2 diagnoser")

    def test_active_first_inactive_kept(self):
        old = _entry(display="Fraktur", status="resolved")
        new = _entry(display="Astma")
        v = pk.build(_patient(), sections=_sections(past_illnesses=[old], problems=[new]),
                     today=TODAY)
        assert [d["display"] for d in v["diagnoses"]] == ["Astma", "Fraktur"]
        assert v["diagnoses"][1]["active"] is False
        assert v["diagnoses"][1]["status_text"] == "läkt"

    def test_empty_sections_are_honest(self):
        v = pk.build(_patient(), sections=[], today=TODAY)
        assert v["diagnoses"] == [] and v["diagnoses_state"] == "ok"
        assert {s["state"] for s in v["sections"]} == {"missing"}
        assert len(v["sections"]) == len(pk.CORE_SECTIONS)
        assert "Graviditet" in v["empty_sections"]

    def test_explicitly_absent_differs_from_missing(self):
        v = pk.build(_patient(), sections=_sections(allergies="absent"), today=TODAY)
        allergies = next(s for s in v["sections"] if s["key"] == "allergies")
        assert allergies["state"] == "absent"
        assert allergies["absent_text"] == "Inga kända allergier"
        assert v["sections"][0]["priority"]          # priority sections first

    def test_unreadable_summary_is_not_empty(self):
        v = pk.build(_patient(), sections=None, today=TODAY)
        assert v["diagnoses_state"] == "unavailable"
        assert v["sections_state"] == "unavailable"

    def test_optional_section_shown_when_it_has_content(self):
        e = _entry(rtype="Observation", display="Resa", code=None)
        v = pk.build(_patient(), sections=_sections(travel_history=[e]), today=TODAY)
        assert "Resor" in [s["title"] for s in v["sections"]]
        assert "Resor" not in v["empty_sections"]

    def test_banners(self):
        v = pk.build(_patient(is_active=False, archived=True),
                     blocks=[{"guid": "b1", "active": True}, {"guid": "b2", "active": False}],
                     consents=[{"guid": "c1", "active": True}], today=TODAY)
        kinds = {b["kind"]: b for b in v["banners"]}
        assert kinds["inactive"]["level"] == "danger"
        assert kinds["block"]["text"] == "Spärr aktiv"
        assert kinds["consent"]["text"] == "1 samtycke i kraft"
        assert "no_unit" in kinds and "archived" in kinds

    def test_unknown_block_state_is_said(self):
        v = pk.build(_patient(), blocks=None, consents=None,
                     units=[{"name": "VC"}], today=TODAY)
        texts = [b["text"] for b in v["banners"]]
        assert "Spärrstatus okänd" in texts and "Samtycken okända" in texts

    def test_quiet_patient_has_no_banners(self):
        v = pk.build(_patient(), units=[{"name": "VC", "caregiver_name": "Region"}], today=TODAY)
        assert v["banners"] == []
        assert v["units"][0]["caregiver_name"] == "Region"

    def test_pop_ids_are_unique(self):
        v = pk.build(_patient(), units=[{"name": "VC"}],
                     sections=_sections(problems=[_entry(), _entry()],
                                        medications=[_entry(rtype="MedicationStatement")]),
                     blocks=[{"guid": "b", "active": True}], today=TODAY)
        ids = [p["id"] for p in _all_pops(v)]
        assert len(ids) == len(set(ids)) and all(re.fullmatch(r"pk-p-\d+", i) for i in ids)


# ── provenance and history ──────────────────────────────────────────────


def _v(n, rj, status="superseded", at="2026-11-0%d 10:00"):
    return {"guid": f"v{n}", "version_id": n, "status": status,
            "created_at": at % n, "resource_json": rj}


class TestProvenance:
    def test_resource_stored_includes_cdr_row(self):
        e = _entry(rid="c-1", cdr={"name": "cdr2", "guid": "cdr-guid"})
        v = pk.build(_patient(), sections=_sections(problems=[e]), today=TODAY)
        stored = v["diagnoses"][0]["prov"]["stored"]
        assert stored[0] == {"where": "eps.pdhc · FHIR Condition", "id": "c-1"}
        assert stored[1] == {"where": "cdr2 · Condition", "id": "cdr-guid"}

    def test_history_newest_first_with_actor_and_changed_fields(self):
        base = {"resourceType": "Condition", "code": {"text": "x"}}
        linked = dict(base, identifier=[{"system": "https://cdr.pdhc.se/fhir/Condition"}],
                      meta={"tag": [{"system": "https://ips.pdhc.se/CodeSystem/provenance",
                                     "code": "derived-from-cdr"}]})
        confirmed = dict(linked, verificationStatus={"coding": [{"code": "confirmed"}]})
        versions = [_v(1, base), _v(2, linked), _v(3, confirmed, "active")]
        audits = [{"event_type": "fhir_create", "at": "2026-11-01T10:00:00",
                   "actor_type": "service", "actor_label": "icd11.pdhc",
                   "resource_guid": "v1", "detail": {}}]
        h = pk.version_history(versions, audits)
        assert [x["text"].split(":")[0] for x in h] == ["Version 3", "Version 2", "Version 1"]
        assert "verifiering" in h[0]["text"] and h[0]["who"] is None
        assert "identifierare" in h[1]["text"] and "derive-conditions-from-cdr" in h[1]["text"]
        assert h[2]["who"] == "icd11.pdhc (service)"
        origin = pk.resource_origin(versions, audits)
        assert origin[0]["text"] == "Skapad via FHIR-API:t"
        assert origin[0]["who"] == "icd11.pdhc (service)"

    def test_nothing_recorded_is_said_not_invented(self):
        versions = [_v(1, {"resourceType": "Condition"}, "active")]
        origin = pk.resource_origin(versions, [])
        assert len(origin) == 1 and origin[0]["who"] is None
        assert "registreras inte" in origin[0]["text"]
        assert pk.resource_origin([], []) == []

    def test_tags_and_endorsement_are_origin(self):
        rj = {"meta": {"tag": [{"system": "urn:pdhc:provenance", "code": "simulated"}]}}
        o = pk.resource_origin([_v(1, rj, "active")], [],
                               {"endorsed_by": [{"name": "Dr Demo", "at": "2026-11-02"}]})
        texts = [x["text"] for x in o]
        assert any("patientsimulator" in t for t in texts)
        assert any(x["who"] == "Dr Demo" for x in o)

    def test_retired_version_is_named(self):
        h = pk.version_history([_v(1, {}), _v(2, {}, "retired")], [])
        assert "tagen ur bruk" in h[0]["text"]

    def test_history_is_capped(self):
        versions = [_v(1, {"n": 0})] + [_v(i, {"n": i}) for i in range(2, 10)]
        e = _entry(rid="r")
        v = pk.build(_patient(), sections=_sections(problems=[e]),
                     records={"resources": {"Condition/r": {"versions": versions, "audits": []}}},
                     today=TODAY)
        p = v["diagnoses"][0]["prov"]
        assert len(p["history"]) == pk.HISTORY_SHOWN and p["history_more"] == 9 - pk.HISTORY_SHOWN
        assert p["history"][0]["text"].startswith("Version 9")

    def test_field_history_names_fields_never_values(self):
        old_name = "Gammalnamn"
        v1 = {"resourceType": "Patient", "name": [{"family": old_name}], "gender": "male",
              "identifier": [{"value": PNR}]}
        v2 = dict(v1, name=[{"family": "Jönsson"}])
        v = pk.build(_patient(), records={"patient": {"versions": [_v(1, v1), _v(2, v2, "active")],
                                                      "audits": []}}, today=TODAY)
        assert v["name_prov"]["history"][0]["text"] == "Version 2: ändrat namn"
        sex = next(f for f in v["fields"] if f["label"] == "Kön")["prov"]
        assert [h["text"] for h in sex["history"]] == ["Version 1: skapad"]
        blob = repr(_all_pops(v))
        assert old_name not in blob
        # The personnummer appears in the field itself, never in a pop-out.
        assert PNR not in blob and PNR.replace("-", "") not in blob

    def test_patient_origin_batch_and_audit(self):
        p = _patient(batch_guid="batch-1", created_at="2026-11-01T09:00:00")
        o = pk.patient_origin(p, [{"event_type": "patient_self_registered", "at": "2026-11-01",
                                   "actor_type": "patient", "actor_label": None}])
        assert o[0]["text"].startswith("Patienten registrerade sig själv")
        assert any("batch-1" in x["text"] for x in o)
        assert pk.patient_origin({"created_at": None}, []) == []

    def test_assignment_history_matches_audits_by_recorded_values(self):
        records = {
            "assignments": [
                {"guid": "a1", "clinic_name": "Gamla", "clinic_guid": "k1",
                 "assigned_at": "2026-01-01T08:00:00", "ended_at": "2026-06-01T08:00:00"},
                {"guid": "a2", "clinic_name": "Nya", "clinic_guid": "k2",
                 "assigned_at": "2026-06-01T08:00:00", "ended_at": None, "origin": "invited"},
            ],
            "assignment_audits": [
                {"event_type": "patient.assignment_ended", "actor_type": "user",
                 "actor_label": "admin@demo", "detail": {"clinic_guid": "k1",
                                                         "ended_at": "2026-06-01T08:00:00"}},
                {"event_type": "patient.assigned", "actor_type": "user",
                 "actor_label": "other@demo", "detail": {"clinic_guid": "k1",
                                                         "assigned_at": "2025-01-01T08:00:00"}},
            ]}
        units = [{"guid": "a2", "name": "Nya", "clinic_guid": "k2", "since": "2026-06-01T08:00:00",
                  "origin": "invited"}]
        v = pk.build(_patient(), units=units, records=records, today=TODAY)
        h = v["units"][0]["prov"]["history"]
        assert h[0]["text"].startswith("Kopplad till Nya")
        ended = next(x for x in h if "avslutad" in x["text"])
        assert ended["who"] == "admin@demo (user)"
        started_old = next(x for x in h if x["text"] == "Kopplad till Gamla")
        assert started_old["who"] is None      # the audit's timestamp does not match
        assert "inbjudan" in v["units"][0]["prov"]["origin"][0]["text"]

    def test_block_and_consent_pops(self):
        v = pk.build(_patient(), units=[{"name": "VC"}],
                     blocks=[{"guid": "b1", "active": True, "scope_type": "clinic",
                              "created_at": "2026-11-01T10:00:00", "created_by": "u1",
                              "lifted_at": None}],
                     consents=[{"guid": "c1", "active": True, "granted_via": "portal",
                                "granted_at": "2026-11-02T10:00:00", "granted_by": None,
                                "revoked_at": None}], today=TODAY)
        block = next(b for b in v["banners"] if b["kind"] == "block")["prov"]
        assert block["stored"] == [{"where": "eps.pdhc · patient_blocks", "id": "b1"}]
        assert block["history"][0]["who"] == "användare u1"
        consent = next(b for b in v["banners"] if b["kind"] == "consent")["prov"]
        assert consent["history"][0]["text"] == "Samtycke lämnat via portal"


# ── the admin page ──────────────────────────────────────────────────────


@pytest.fixture
def seeded(client, db):
    from app.models.audit_log import AuditLog
    from app.models.clinic import Clinic
    from app.models.patient_index import PatientClinicAssignment, PatientIndex
    from app.services import fhir_service

    org = str(uuid.uuid4())
    vg = Clinic(name="Region Demo", organisation_guid=org, care_organisation_guid=org)
    unit = Clinic(name="VC Demo", organisation_guid=str(uuid.uuid4()), care_organisation_guid=org)
    db.session.add_all([vg, unit]); db.session.flush()
    pid = str(uuid.uuid4())
    pres = fhir_service.create_resource("Patient", {"resourceType": "Patient", "id": pid})
    db.session.flush()
    p = db.session.query(PatientIndex).filter_by(resource_id=pid).first()
    if p is None:
        p = PatientIndex(fhir_resource_guid=pres.guid, resource_id=pid)
        db.session.add(p)
    p.family_name, p.given_name = "Kortsson", "Karin"
    p.birth_date, p.gender, p.identifier_value = date(1961, 9, 23), "female", PNR
    db.session.flush()
    db.session.add(PatientClinicAssignment(patient_guid=p.guid, clinic_guid=unit.guid))
    c = fhir_service.create_resource("Condition", {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003",
                             "display": "Hypertoni"}]}}, patient_guid=p.guid)
    db.session.add(AuditLog(event_type="fhir_create", actor_type="service",
                            actor_label="demo.caller", resource_guid=c.guid,
                            created_at=datetime.now(timezone.utc)))
    db.session.commit()
    return p


def test_admin_page_renders_card_above_administration(client, seeded):
    body = client.get(f"/admin/patients/{seeded.guid}").get_data(as_text=True)
    assert "patientkort.css" in body
    card, admin = body.split(">Administration<", 1)
    age = pk.age_years(date(1961, 9, 23), date.today())
    assert "Kortsson, Karin" in card and "Kvinna" in card and f"{age} år" in card
    assert "VC Demo" in card and "Region Demo" in card
    assert "Hypertoni" in card and "ej förankrad i CDR" in card
    assert "demo.caller (service)" in card                 # the audit actor, in the pop-out
    assert "Inga registrerade" in card
    # Administration still fully there.
    for marker in ("Add Clinical Resource", "Create IPS Card", "Byt klinik", "Registerdata"):
        assert marker in admin


def _pop_texts(html):
    """The full text of every pop-out, by parsing (span nesting tracked)."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth, self.pops = 0, []

        def handle_starttag(self, tag, attrs):
            if self.depth:
                if tag == "span":
                    self.depth += 1
            elif tag == "span" and "pk-pop" in (dict(attrs).get("class") or "").split():
                self.depth = 1
                self.pops.append("")

        def handle_endtag(self, tag):
            if self.depth and tag == "span":
                self.depth -= 1

        def handle_data(self, data):
            if self.depth:
                self.pops[-1] += data

    parser = P()
    parser.feed(html)
    return parser.pops


def test_personnummer_only_in_the_card_field(client, seeded):
    body = client.get(f"/admin/patients/{seeded.guid}").get_data(as_text=True)
    card = body.split(">Administration<", 1)[0]
    pops = _pop_texts(card)
    # Control: every pop-out is captured whole, through its last section.
    assert pops and len(pops) == card.count('class="pk-pop"')
    assert all("Historik" in pop for pop in pops)
    assert all(PNR not in pop for pop in pops)
    assert card.count(PNR) == 1
