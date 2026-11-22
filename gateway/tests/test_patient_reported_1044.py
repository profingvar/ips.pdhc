"""#1044 — the EPS takes of patient-reported material only what care endorsed.

Contract s4.4: an endorsement row (`endorses_guid` set, `data_origin` NULL)
is the only source. The first half of this file is the Questionnaire itself.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import cdr_patient_reported_derivation as der
from app.services import euips_sections as euips
from app.services import euips_summary as summ

HERE = os.path.dirname(__file__)
#: The form's home, in the workspace repo. Absent inside the service image.
PLANS_FILE = os.path.normpath(os.path.join(
    HERE, "..", "..", "..", "plans", "PROMs", "eps_patient_v1.json"))
PREFIXES = ("allergy.", "medication.", "history.", "vaccination.", "contact.")
SIMPLE_TYPES = {"group", "display", "boolean", "string", "text", "date", "integer", "choice"}


def _q(path=der.QUESTIONNAIRE_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _walk(items):
    for it in items or []:
        yield it
        yield from _walk(it.get("item"))


# ------------------------------------------------------------ the Questionnaire

@pytest.fixture(params=["copy", "plans"])
def q(request):
    if request.param == "plans":
        if not os.path.exists(PLANS_FILE):
            pytest.skip("plans/PROMs is not in this checkout (service image)")
        return _q(PLANS_FILE)
    return _q()


def test_the_services_copy_of_the_form_is_byte_identical_to_the_plans_file():
    if not os.path.exists(PLANS_FILE):
        pytest.skip("plans/PROMs is not in this checkout (service image)")
    with open(PLANS_FILE, "rb") as a, open(der.QUESTIONNAIRE_PATH, "rb") as b:
        assert a.read() == b.read()


def test_it_is_a_wellformed_questionnaire_with_the_contracts_identity(q):
    assert q["resourceType"] == "Questionnaire"
    assert q["url"] == "https://plan.pdhc.se/fhir/Questionnaire/eps-patient"
    assert q["version"] == "1" and q["status"] == "draft"
    items = list(_walk(q["item"]))
    assert items
    for it in items:
        assert it.get("linkId") and it.get("text"), it
        assert it["type"] in SIMPLE_TYPES, it["linkId"]
        assert (it["type"] == "group") == bool(it.get("item")), it["linkId"]
        if it["type"] == "choice":
            codes = [o["valueCoding"]["code"] for o in it["answerOption"]]
            assert len(codes) >= 2 and len(codes) == len(set(codes))
            assert all(o["valueCoding"].get("display") for o in it["answerOption"])
        else:
            assert "answerOption" not in it


def test_linkids_are_unique(q):
    ids = [it["linkId"] for it in _walk(q["item"])]
    assert len(ids) == len(set(ids))


def test_every_answerable_item_has_one_of_the_five_prefixes(q):
    answerable = [it["linkId"] for it in _walk(q["item"]) if it["type"] not in ("group", "display")]
    assert len(answerable) == 20
    assert [i for i in answerable if not i.startswith(PREFIXES)] == []
    groups = [it["linkId"] for it in _walk(q["item"]) if it["type"] == "group"]
    assert [g for g in groups if not g.startswith(PREFIXES)] == []


def test_each_section_opens_with_an_explicit_none_known_choice_and_one_repeating_group(q):
    ids = {it["linkId"]: it for it in _walk(q["item"])}
    for s in der.SECTIONS:
        status = ids[f"{s}.status"]
        assert status["type"] == "choice" and status["required"] is True
        assert [o["valueCoding"]["code"] for o in status["answerOption"]] == ["has", "none", "unknown"]
        group = ids[f"{s}.entry"]
        assert group["type"] == "group" and group["repeats"] is True
        (ew,) = group["enableWhen"]
        assert ew["question"] == f"{s}.status" and ew["operator"] == "="
        assert ew["answerCoding"]["code"] == "has"
        children = [c["linkId"] for c in group["item"]]
        assert f"{s}.{der.ANCHOR[s]}" == children[0], "the anchor is the first, required field"
        assert group["item"][0]["required"] is True


def test_there_is_no_diagnosis_section(q):
    text = json.dumps(q, ensure_ascii=False).lower()
    assert not [i["linkId"] for i in _walk(q["item"]) if "diagnos" in i["linkId"]]
    assert "diagnoser fyller du inte i här" in text


def test_the_derivations_closed_lists_are_the_forms(q):
    ids = {it["linkId"]: it for it in _walk(q["item"])}
    for link, field in (("allergy.severity", "severity"), ("medication.prescribed", "prescribed"),
                        ("allergy.status", "status")):
        codes = {o["valueCoding"]["code"] for o in ids[link]["answerOption"]}
        assert codes == set(der.CHOICES[field])


# ------------------------------------------------------------------ the rule

P = "462c1906-d09f-415b-80af-e1b094b54451"
NURSE = {"reviewed_by_user_guid": "0a1b2c3d-0000-4000-8000-000000000001",
         "reviewed_by_name": "Sara Sjuksköterska", "reviewed_at": "2026-11-22T09:00:00+00:00",
         "author_org_guid": "11111111-2222-4333-8444-555555555555"}
DOCTOR = {"reviewed_by_user_guid": "0a1b2c3d-0000-4000-8000-000000000002",
          "reviewed_by_name": "Lars Läkare", "reviewed_at": "2026-11-22T10:00:00+00:00"}


def original(guid, link_id, value, status="pending", patient=P, **kw):
    return {"cdr": "cdr1", "guid": guid, "patient_guid": patient, "link_id": link_id,
            "value": value, "data_origin": "patient_generated", "endorses_guid": None,
            "review_status": status, **kw}


def endorsement(guid, of, link_id, value, who=NURSE, patient=P, **kw):
    return {"cdr": "cdr1", "guid": guid, "patient_guid": patient, "link_id": link_id,
            "value": value, "data_origin": None, "endorses_guid": of, **who, **kw}


def _plan(rows, current=None):
    return der.plan(rows, current or {})


def test_an_original_alone_derives_nothing():
    changes, report = _plan([original("o1", "allergy.substance", "Penicillin", status="endorsed")])
    assert changes == [] and report["sources"] == 0 and report["originals_ignored"] == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_a_pending_or_rejected_answer_derives_nothing(status):
    changes, report = _plan([original("o1", "medication.name", "Waran", status=status)])
    assert changes == [] and report["sources"] == 0


def test_an_endorsement_derives_ONE_entry_with_its_cdr_link_and_endorser():
    rows = [original("o1", "allergy.substance", "Penicillin", status="endorsed"),
            endorsement("e1", "o1", "allergy.substance", "Penicillin")]
    ((action, rtype, rid, pg, js),), report = _plan(rows)
    assert (action, rtype, pg) == ("create", "AllergyIntolerance", P)
    assert rid == der.eps_id_for("e1") == js["id"]
    assert js["identifier"] == [{"system": der.CDR_IDENTIFIER_SYSTEM, "value": "e1",
                                 "assigner": {"display": "cdr1"}}], \
        "the link is to the ENDORSEMENT row, never to the original"
    assert js["code"] == {"text": "Penicillin"}, "free text stays text: no coding"
    assert js["patient"] == {"reference": f"Patient/{P}"}
    assert der.ENDORSED_TAG in js["meta"]["tag"]
    prov = der.endorsement_of(js)
    assert prov["origin"] == "patient_reported" and prov["informant"] == "patient"
    assert prov["endorsed_by"] == [{"name": "Sara Sjuksköterska",
                                    "user_guid": NURSE["reviewed_by_user_guid"],
                                    "org_guid": NURSE["author_org_guid"],
                                    "at": NURSE["reviewed_at"]}]
    funcs = [p["function"]["coding"][0]["code"] for p in js["participant"]]
    assert funcs == ["informant", "verifier"]
    assert js["participant"][0]["actor"] == {"reference": f"Patient/{P}"}


def test_an_amended_endorsement_uses_the_AMENDED_value():
    rows = [original("o1", "medication.name", "Waran 5 mg", status="endorsed"),
            endorsement("e1", "o1", "medication.name", "Warfarin 2,5 mg")]
    ((_, rtype, _, _, js),), _ = _plan(rows)
    assert rtype == "MedicationStatement"
    assert js["medication"] == {"concept": {"text": "Warfarin 2,5 mg"}}
    assert "Waran 5 mg" not in json.dumps(js, ensure_ascii=False)


def test_a_rerun_plans_nothing():
    rows = [endorsement("e1", "o1", "allergy.substance", "Penicillin"),
            endorsement("e2", "o2", "allergy.status", "none", patient=str(uuid.UUID(int=7)))]
    first, _ = _plan(rows)
    assert len(first) == 2
    current = {rid: json.loads(json.dumps(js)) for _, _, rid, _, js in first}
    assert _plan(rows, current)[0] == []


def test_a_patient_generated_row_dressed_as_an_endorsement_REFUSES_the_run():
    smuggled = {**endorsement("x1", "o1", "allergy.substance", "Penicillin"),
                "data_origin": "patient_generated", "review_status": "endorsed"}
    good = endorsement("e2", "o2", "medication.name", "Alvedon")
    with pytest.raises(ValueError, match="never an EPS source"):
        _plan([good, smuggled])
    assert der.is_source(smuggled) is False and der.is_source(good) is True


def test_an_export_that_does_not_state_data_origin_is_refused():
    row = endorsement("e1", "o1", "allergy.substance", "Penicillin")
    del row["data_origin"]
    with pytest.raises(ValueError, match="does not state data_origin"):
        _plan([row])


def test_an_endorsement_without_an_author_is_refused():
    row = endorsement("e1", "o1", "allergy.substance", "Penicillin",
                      who={"reviewed_by_name": "Sara Sjuksköterska",
                           "reviewed_at": "2026-11-22T09:00:00+00:00"})
    with pytest.raises(ValueError, match="names no author"):
        _plan([row])


def test_an_endorsement_of_a_rejected_original_is_refused():
    with pytest.raises(ValueError, match="review_status is 'rejected'"):
        _plan([original("o1", "allergy.substance", "Penicillin", status="rejected"),
               endorsement("e1", "o1", "allergy.substance", "Penicillin")])


def test_two_endorsements_of_one_original_are_refused():
    with pytest.raises(ValueError, match="two endorsement rows"):
        _plan([endorsement("e1", "o1", "allergy.substance", "Penicillin"),
               endorsement("e2", "o1", "allergy.substance", "Pc")])


def test_a_care_row_that_endorses_nothing_is_not_this_derivations_business():
    row = {"cdr": "cdr1", "guid": "b1", "patient_guid": P, "link_id": "allergy.substance",
           "value": "Penicillin", "data_origin": None, "endorses_guid": None}
    assert _plan([row])[0] == []


# ------------------------------------------------------------ anchors, details

def test_details_attach_by_group_and_never_by_guess():
    rows = [endorsement("a1", "o1", "allergy.substance", "Penicillin", group="0"),
            endorsement("a2", "o2", "allergy.reaction", "Utslag", group="0", who=DOCTOR),
            endorsement("a3", "o3", "allergy.severity", "moderate", group="0"),
            endorsement("b1", "o4", "allergy.substance", "Jordnötter", group="1")]
    changes, report = _plan(rows)
    by = {js["code"]["text"]: js for *_, js in changes}
    assert set(by) == {"Penicillin", "Jordnötter"} and report["unattached"] == []
    assert by["Penicillin"]["reaction"] == [{"manifestation": [{"concept": {"text": "Utslag"}}],
                                             "severity": "moderate"}]
    assert "reaction" not in by["Jordnötter"]
    assert [i["value"] for i in by["Penicillin"]["identifier"]] == ["a1", "a2", "a3"], \
        "the anchor first, then every detail row"
    assert [w["name"] for w in der.endorsement_of(by["Penicillin"])["endorsed_by"]] == \
        ["Sara Sjuksköterska", "Lars Läkare"]


def test_without_a_group_a_detail_is_attached_only_when_there_is_ONE_anchor():
    one = [endorsement("a1", "o1", "allergy.substance", "Penicillin"),
           endorsement("a2", "o2", "allergy.reaction", "Utslag")]
    ((*_, js),), report = _plan(one)
    assert js["reaction"][0]["manifestation"][0]["concept"]["text"] == "Utslag"
    two = one + [endorsement("b1", "o3", "allergy.substance", "Jordnötter")]
    changes, report = _plan(two)
    assert report["unattached"] == ["a2"]
    assert all("reaction" not in js for *_, js in changes) and len(changes) == 2


def test_a_detail_whose_anchor_was_not_endorsed_is_unattached_not_an_entry():
    changes, report = _plan([original("o1", "allergy.substance", "Penicillin", status="rejected"),
                             endorsement("a2", "o2", "allergy.reaction", "Utslag")])
    assert changes == [] and report["unattached"] == ["a2"]


def test_a_coded_answer_is_recognised_by_code_OR_by_the_forms_display():
    q = {i["linkId"]: i for i in _walk(_q()["item"])}
    display = next(o["valueCoding"]["display"] for o in q["allergy.severity"]["answerOption"]
                   if o["valueCoding"]["code"] == "severe")
    for value in ("severe", display, {"code": "severe", "display": display}):
        ((*_, js),), _ = _plan([endorsement("a1", "o1", "allergy.substance", "Bi"),
                                endorsement("a2", "o2", "allergy.reaction", "Svullnad"),
                                endorsement("a3", "o3", "allergy.severity", value)])
        assert js["reaction"][0]["severity"] == "severe", value
    ((*_, js),), _ = _plan([endorsement("a1", "o1", "allergy.substance", "Bi"),
                            endorsement("a2", "o2", "allergy.reaction", "Svullnad"),
                            endorsement("a3", "o3", "allergy.severity", "ganska")])
    assert "severity" not in js["reaction"][0], "an unrecognised answer is not mapped to the nearest"


# ------------------------------------------------------------ the five mappings

def _one(rows):
    ((_, rtype, _, _, js),), report = _plan(rows)
    return rtype, js


def test_medication_is_text_only_with_the_patient_as_information_source():
    rtype, js = _one([endorsement("m1", "o1", "medication.name", "Alvedon"),
                      endorsement("m2", "o2", "medication.dose", "500 mg"),
                      endorsement("m3", "o3", "medication.frequency", "vid behov"),
                      endorsement("m4", "o4", "medication.indication", "huvudvärk"),
                      endorsement("m5", "o5", "medication.prescribed", "Nej")])
    assert rtype == "MedicationStatement" and js["status"] == "recorded"
    assert js["medication"] == {"concept": {"text": "Alvedon"}}
    assert js["dosage"] == [{"text": "500 mg, vid behov"}]
    assert js["reason"] == [{"concept": {"text": "huvudvärk"}}]
    assert js["informationSource"] == [{"reference": f"Patient/{P}"}]
    assert js["note"] == [{"text": "Utskrivet av vården enligt patienten: nej"}]
    assert "coding" not in json.dumps(js["medication"])
    assert euips.section_matches(euips.BY_KEY["medications"], rtype, js)


def test_history_is_a_PAST_ILLNESS_and_never_a_problem_list_entry():
    rtype, js = _one([endorsement("h1", "o1", "history.condition", "Blindtarmsinflammation"),
                      endorsement("h2", "o2", "history.year", 1998)])
    assert rtype == "Condition" and js["code"] == {"text": "Blindtarmsinflammation"}
    assert js["onsetDateTime"] == "1998" and "verificationStatus" not in js
    assert euips.section_matches(euips.BY_KEY["past_illnesses"], rtype, js)
    assert not euips.section_matches(euips.BY_KEY["problems"], rtype, js)


def test_vaccination_keeps_the_date_or_says_it_is_unknown():
    rtype, js = _one([endorsement("v1", "o1", "vaccination.vaccine", "TBE"),
                      endorsement("v2", "o2", "vaccination.date", "2024-05-02")])
    assert rtype == "Immunization" and js["vaccineCode"] == {"text": "TBE"}
    assert js["occurrenceDateTime"] == "2024-05-02" and js["primarySource"] is False
    _, bare = _one([endorsement("v1", "o1", "vaccination.vaccine", "TBE")])
    assert bare["occurrenceString"] == "okänt datum" and "occurrenceDateTime" not in bare


def test_a_contact_is_a_related_person_with_text_only():
    rtype, js = _one([endorsement("c1", "o1", "contact.name", "Eva Exempel"),
                      endorsement("c2", "o2", "contact.relation", "dotter"),
                      endorsement("c3", "o3", "contact.phone", "070-000 00 00")])
    assert rtype == "RelatedPerson" and js["patient"] == {"reference": f"Patient/{P}"}
    assert js["name"] == [{"text": "Eva Exempel"}]
    assert js["relationship"] == [{"text": "dotter"}]
    assert js["telecom"] == [{"system": "phone", "value": "070-000 00 00"}]


def test_free_text_is_escaped_in_the_narrative():
    _, js = _one([endorsement("a1", "o1", "allergy.substance", "<script>x</script>")])
    assert "<script>" not in js["text"]["div"] and "&lt;script&gt;" in js["text"]["div"]
    assert "godkänd av Sara Sjuksköterska 2026-11-22" in js["text"]["div"]


def test_none_known_becomes_the_sections_absent_assertion_and_unknown_becomes_nothing():
    rtype, js = _one([endorsement("s1", "o1", "allergy.status", "none")])
    assert rtype == "AllergyIntolerance" and euips.is_absent_assertion(js)
    assert euips.absent_section_key(js) == "allergies" and der.endorsement_of(js)
    changes, report = _plan([endorsement("s2", "o2", "allergy.status", "unknown"),
                             endorsement("s3", "o3", "history.status", "none"),
                             endorsement("s4", "o4", "medication.status", "has"),
                             endorsement("s5", "o5", "contact.status", "kanske")])
    assert changes == []
    assert report["no_information"] == ["s2"] and report["none_without_absent_code"] == ["s3"]
    assert report["unrecognised"] == ["s5"]


def test_a_derived_entry_whose_endorsement_left_the_export_is_REPORTED_and_kept():
    first, _ = _plan([endorsement("e1", "o1", "allergy.substance", "Penicillin")])
    current = {rid: js for _, _, rid, _, js in first}
    current["care-own"] = {"resourceType": "AllergyIntolerance", "id": "care-own"}
    changes, report = _plan([], current)
    assert changes == [] and report["orphaned"] == [der.eps_id_for("e1")]


def test_a_changed_export_gives_a_new_version_not_a_second_entry():
    first, _ = _plan([endorsement("e1", "o1", "allergy.substance", "Penicillin")])
    current = {rid: js for _, _, rid, _, js in first}
    ((action, _, rid, _, js),), _ = _plan(
        [endorsement("e1", "o1", "allergy.substance", "Penicillin"),
         endorsement("e2", "o2", "allergy.reaction", "Utslag")], current)
    assert action == "update" and rid in current and "reaction" in js


# ------------------------------------------------ attester, summary, conditions

def test_each_endorser_attests_once_at_their_latest_endorsement():
    changes, _ = _plan([endorsement("e1", "o1", "allergy.substance", "Penicillin"),
                        endorsement("e2", "o2", "medication.name", "Alvedon",
                                    who={**NURSE, "reviewed_at": "2026-11-23T08:00:00+00:00"}),
                        endorsement("e3", "o3", "history.condition", "Astma", who=DOCTOR)])
    att = der.attesters([js for *_, js in changes] + [{"resourceType": "Condition"}])
    assert [a["party"]["display"] for a in att] == ["Sara Sjuksköterska", "Lars Läkare"]
    assert att[0]["time"] == "2026-11-23T08:00:00+00:00"
    assert att[0]["mode"]["coding"][0] == {
        "system": "http://hl7.org/fhir/composition-attestation-mode",
        "code": "professional", "display": "Professional"}
    assert att[0]["party"]["identifier"] == {"system": der.SSO_USER_SYSTEM,
                                             "value": NURSE["reviewed_by_user_guid"]}


def test_the_existing_conditions_derivation_refuses_a_patient_generated_row():
    from app.services import cdr_condition_derivation as cond
    row = {"cdr": "cdr2", "guid": "c9", "patient_guid": P, "data_origin": "patient_generated",
           "raw_json": {"code": {"text": "Diabetes"}}}
    with pytest.raises(ValueError, match="never an EPS source"):
        cond.plan([row], {})
    assert len(cond.plan([{**row, "data_origin": None}], {})) == 1


# ------------------------------------------------------- through the real CLI

def _patient(db):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res); db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     family_name="Endorsed", given_name="Test")
    db.session.add(p); db.session.commit()
    res.patient_guid = p.guid; db.session.commit()
    return p


def _export(tmp_path, rows):
    f = tmp_path / "export.json"
    f.write_text(json.dumps(rows))
    return str(f)


def _cli(client, *a):
    return client.application.test_cli_runner().invoke(
        args=["derive-patient-reported-from-cdr", *a])


def _derived(db):
    return [r for r in db.session.query(FhirResource).filter_by(status="active")
            if der.is_derived(r.resource_json)]


def test_cli_is_a_dry_run_by_default_and_expect_mismatch_refuses(client, db, tmp_path):
    pg = str(_patient(db).guid)
    path = _export(tmp_path, [
        original("o1", "allergy.substance", "Penicillin", status="endorsed", patient=pg),
        endorsement("e1", "o1", "allergy.substance", "Penicillin", patient=pg),
        original("o2", "medication.name", "Waran", status="rejected", patient=pg),
        original("o3", "history.condition", "Astma", patient=pg)])
    res = _cli(client, path)
    assert res.exit_code == 0 and "dry run" in res.output and "planned {'create': 1}" in res.output
    assert "2 patient-generated original(s) ignored" not in res.output  # three originals
    assert "3 patient-generated original(s) ignored" in res.output
    assert _derived(db) == []
    res = _cli(client, path, "--apply", "--expect", "2")
    assert res.exit_code != 0 and "--expect 2 but 1 planned" in res.output
    assert _derived(db) == []
    res = _cli(client, path, "--apply", "--expect", "1")
    assert res.exit_code == 0, res.output
    (row,) = _derived(db)
    assert row.resource_type == "AllergyIntolerance" and str(row.patient_guid) == pg
    assert row.resource_json["code"] == {"text": "Penicillin"}
    res = _cli(client, path, "--apply", "--expect", "0")
    assert res.exit_code == 0 and len(_derived(db)) == 1, "a re-run writes nothing"
    assert db.session.query(FhirResource).filter_by(status="superseded").count() == 0


def test_cli_refuses_a_smuggled_row_and_an_unknown_patient_and_writes_nothing(client, db, tmp_path):
    pg = str(_patient(db).guid)
    smuggled = {**endorsement("x1", "o1", "allergy.substance", "Penicillin", patient=pg),
                "data_origin": "patient_generated"}
    res = _cli(client, _export(tmp_path, [
        endorsement("e2", "o2", "medication.name", "Alvedon", patient=pg), smuggled]), "--apply")
    assert res.exit_code != 0 and "never an EPS source" in res.output and _derived(db) == []
    res = _cli(client, _export(tmp_path, [
        endorsement("e2", "o2", "medication.name", "Alvedon", patient=str(uuid.uuid4()))]), "--apply")
    assert res.exit_code != 0 and "has no patient" in res.output and _derived(db) == []


def test_the_document_names_the_endorser_as_attester_and_the_summary_shows_provenance(
        client, db, tmp_path):
    from app.services.ips_generator import generate_ips_bundle
    p = _patient(db)
    pg = str(p.guid)
    path = _export(tmp_path, [
        endorsement("e1", "o1", "allergy.substance", "Penicillin", patient=pg),
        endorsement("e3", "o3", "contact.name", "Eva Exempel", patient=pg, who=DOCTOR)])
    assert _cli(client, path, "--apply", "--expect", "2").exit_code == 0
    bundle = generate_ips_bundle(p)
    comp = bundle["entry"][0]["resource"]
    assert [(a["mode"]["coding"][0]["code"], a["party"]["display"]) for a in comp.get("attester", [])] == \
        [("professional", "Sara Sjuksköterska"), ("professional", "Lars Läkare")]

    rows = db.session.query(FhirResource).filter_by(patient_guid=p.guid, status="active").all()
    allergies = next(s for s in summ.compose(rows) if s["key"] == "allergies")
    (e,) = allergies["entries"]
    assert e["display"] == "Penicillin" and e["code"] is None and e["system"] is None
    assert e["cdr_backed"] is True and e["cdr"] == {"name": "cdr1", "guid": "e1"}
    assert e["provenance"] is not None and e["provenance"]["informant"] == "patient"
    assert e["provenance"]["endorsed_by"][0]["name"] == "Sara Sjuksköterska"


def test_a_care_entry_has_no_patient_provenance(db):
    class Row:
        resource_type, resource_id = "AllergyIntolerance", "x"
        resource_json = {"resourceType": "AllergyIntolerance", "id": "x", "code": {"text": "Latex"}}
    assert summ.entry(Row())["provenance"] is None


def test_the_summary_route_shows_only_the_CURRENT_version_of_an_entry(client, db, tmp_path):
    p = _patient(db)
    pg = str(p.guid)
    a = endorsement("e1", "o1", "allergy.substance", "Penicillin", patient=pg)
    assert _cli(client, _export(tmp_path, [a]), "--apply").exit_code == 0
    b = endorsement("e2", "o2", "allergy.reaction", "Utslag", patient=pg)
    assert _cli(client, _export(tmp_path, [a, b]), "--apply", "--expect", "1").exit_code == 0
    assert db.session.query(FhirResource).filter_by(status="superseded").count() == 1
    body = client.get(f"/api/v1/patients/{pg}/euips-summary").get_json()
    allergies = next(s for s in body["sections"] if s["key"] == "allergies")
    assert len(allergies["entries"]) == 1


def test_the_status_route_does_not_count_a_superseded_version(client, db):
    p = _patient(db)
    db.session.add(FhirResource(
        resource_type="AllergyIntolerance", resource_id="old", status="superseded",
        patient_guid=p.guid,
        resource_json={"resourceType": "AllergyIntolerance", "id": "old",
                       "code": {"text": "Penicillin"}}))
    db.session.commit()
    body = client.get(f"/api/v1/patients/{p.guid}/euips-sections").get_json()
    allergies = next(s for s in body["sections"] if s["key"] == "allergies")
    assert allergies["status"] == euips.MISSING
