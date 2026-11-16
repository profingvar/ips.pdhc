"""#984 — the EPS problems section is derived from the CDR."""
import pytest

from app.services import cdr_condition_derivation as der

P = "462c1906-d09f-415b-80af-e1b094b54451"


def _eps(rid="e1"):
    return {"resourceType": "Condition", "id": rid, "subject": {"reference": f"Patient/{P}"},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "49436004"}]}}


def _cdr_from_eps(guid="c1", ips_id="e1"):
    return {"cdr": "cdr2", "guid": guid, "patient_guid": P,
            "raw_json": {"identifier": [{"system": der.IPS_IDENTIFIER_SYSTEM, "value": ips_id}],
                         "code": {"coding": [{"system": "https://termbank.pdhc.se/CodeSystem/snomed", "code": "49436004"}]}}}


def _cdr_icd11(guid="c9"):
    return {"cdr": "cdr2", "guid": guid, "patient_guid": P,
            "raw_json": {"code": {"text": "Diabetes mellitus typ 2", "coding": [
                {"system": "http://id.who.int/icd/release/11/mms", "code": "5A11"}]},
                "recordedDate": "2026-10-23", "text": {"div": "cdr's"},
                "meta": {"security": [{"system": "urn:pdhc:source-org", "code": "x"}]}}}


def test_an_eps_condition_backfilled_to_the_cdr_is_LINKED_not_copied():
    (action, rid, pg, js), = der.plan([_cdr_from_eps()], {"e1": _eps()})
    assert (action, rid, pg) == ("link", "e1", P)
    assert {"system": der.CDR_IDENTIFIER_SYSTEM, "value": "c1", "assigner": {"display": "cdr2"}} in js["identifier"]
    assert der.DERIVED_TAG in js["meta"]["tag"]
    assert js["code"] == _eps()["code"], "the EPS content is not rewritten"
    assert der.is_cdr_backed(js) and not der.is_cdr_backed(_eps())


def test_a_cdr_condition_with_no_eps_twin_is_CREATED_with_only_clinical_content():
    (action, rid, pg, js), = der.plan([_cdr_icd11()], {})
    assert action == "create" and rid == der.eps_id_for("c9") and js["id"] == rid
    assert js["code"]["coding"][0]["code"] == "5A11"
    assert js["subject"] == {"reference": f"Patient/{P}"}
    assert "text" not in js and "security" not in js["meta"], "the CDR's own labels stay in the CDR"
    assert der.is_cdr_backed(js)


def test_a_rerun_plans_nothing():
    first = der.plan([_cdr_from_eps(), _cdr_icd11()], {"e1": _eps()})
    current = {rid: js for _, rid, _, js in first}
    assert der.plan([_cdr_from_eps(), _cdr_icd11()], current) == []


def test_a_cdr_row_naming_a_missing_eps_condition_is_an_error_not_a_create():
    with pytest.raises(ValueError, match="does not have"):
        der.plan([_cdr_from_eps(ips_id="gone")], {})


def test_link_does_not_mutate_its_input():
    e = _eps()
    der.link(e, "c1", "cdr2")
    assert "identifier" not in e and "meta" not in e


# ------------------------------------------------- the summary says which entries are backed

class _Row:
    def __init__(self, rj):
        self.resource_type, self.resource_id, self.resource_json = "Condition", rj["id"], rj


def test_a_summary_entry_states_whether_a_cdr_row_backs_it():
    from app.services.euips_summary import entry
    linked = der.link({**_eps(), "onsetDateTime": "2020-01-01"}, "c1", "cdr2")
    e = entry(_Row(linked))
    assert e["cdr_backed"] is True and e["cdr"] == {"name": "cdr2", "guid": "c1"}
    assert e["onset"] == "2020-01-01"
    bare = entry(_Row(_eps()))
    assert bare["cdr_backed"] is False and bare["cdr"] is None
