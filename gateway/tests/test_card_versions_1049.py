"""#1049 (contract s7.2/s7.4): per patient and section, only the LATEST
endorsed card version is an EPS source; an older endorsed version is replaced,
so an endorsed removal removes. v1 rows (no card_version) keep the #1044 rule.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.models.fhir_resource import FhirResource
from app.services import cdr_patient_reported_derivation as der
from tests.test_patient_reported_1044 import (
    NURSE, P, _cli, _derived, _export, _patient, endorsement)

V1, V2, V3 = ("c0000000-0000-4000-8000-000000000001",
              "c0000000-0000-4000-8000-000000000002",
              "c0000000-0000-4000-8000-000000000003")
T1, T2, T3 = "2026-11-22T09:00:00+00:00", "2026-11-23T09:00:00+00:00", "2026-11-24T09:00:00+00:00"


def card(guid, link_id, value, version, at, section=None, patient=P, group="g1"):
    return endorsement(guid, f"o-{guid}", link_id, value, patient=patient,
                       who={**NURSE, "reviewed_at": at}, card_version=version,
                       card_section=section or link_id.split(".")[0], group=group)


def _texts(changes, action="create"):
    return sorted(js["code"]["text"] for a, _, _, _, js in changes if a == action)


def test_only_the_latest_endorsed_version_derives():
    rows = [card("a1", "allergy.substance", "Penicillin", V1, T1, group="x"),
            card("a2", "allergy.substance", "Nötter", V1, T1, group="y"),
            card("b1", "allergy.substance", "Penicillin", V2, T2, group="x")]
    changes, report = der.plan(rows, {})
    assert _texts(changes) == ["Penicillin"]
    ((_, _, rid, _, js),) = changes
    assert rid == der.eps_id_for("b1") and der.card_version_of(js) == V2
    assert sorted(report["replaced_by_newer_card"]) == ["a1", "a2"]


def test_order_is_by_reviewed_at_not_by_position_or_version_string():
    rows = [card("b1", "allergy.substance", "Latex", V1, T3),
            card("a1", "allergy.substance", "Penicillin", V3, T1)]
    changes, _ = der.plan(rows, {})
    assert _texts(changes) == ["Latex"]


def test_an_endorsed_removal_RETIRES_the_entry_from_the_older_version():
    old = [card("a1", "allergy.substance", "Penicillin", V1, T1, group="x"),
           card("a2", "allergy.substance", "Nötter", V1, T1, group="y")]
    first, _ = der.plan(old, {})
    current = {rid: json.loads(json.dumps(js)) for _, _, rid, _, js in first}
    # the patient removed the nut allergy; care endorsed V2
    changes, report = der.plan(old + [card("b1", "allergy.substance", "Penicillin", V2, T2,
                                           group="x")], current)
    retired = sorted(rid for a, _, rid, _, _ in changes if a == "retire")
    assert retired == sorted([der.eps_id_for("a1"), der.eps_id_for("a2")])
    assert _texts(changes) == ["Penicillin"]
    assert report["orphaned"] == []


def test_v1_rows_are_untouched_by_a_card_version():
    v1 = endorsement("e1", "o1", "allergy.substance", "Latex")      # no card_version
    first, _ = der.plan([v1], {})
    current = {rid: js for _, _, rid, _, js in first}
    assert der.card_version_of(next(iter(current.values()))) is None
    changes, _ = der.plan([v1, card("b1", "allergy.substance", "Penicillin", V2, T2)], current)
    assert [a for a, *_ in changes] == ["create"] and _texts(changes) == ["Penicillin"]


def test_another_section_or_patient_is_not_replaced():
    other = str(uuid.UUID(int=9))
    rows = [card("a1", "allergy.substance", "Penicillin", V1, T1),
            card("m1", "medication.name", "Alvedon", V2, T2),
            card("q1", "allergy.substance", "Latex", V3, T3, patient=other)]
    changes, report = der.plan(rows, {})
    assert len(changes) == 3 and report["replaced_by_newer_card"] == []


def test_a_rerun_plans_nothing_and_retires_nothing_twice():
    rows = [card("a1", "allergy.substance", "Penicillin", V1, T1),
            card("b1", "allergy.substance", "Latex", V2, T2)]
    first, _ = der.plan(rows, {})
    current = {rid: js for _, _, rid, _, js in first}
    assert der.plan(rows, current)[0] == []


def test_an_export_that_would_bring_back_a_retired_entry_is_refused():
    with pytest.raises(ValueError, match="older than the EPS"):
        der.plan([card("a1", "allergy.substance", "Penicillin", V1, T1)], {},
                 retired={der.eps_id_for("a1")})


def test_a_version_spanning_two_sections_or_a_contradicting_card_section_is_refused():
    with pytest.raises(ValueError, match="spans"):
        der.plan([card("a1", "allergy.substance", "X", V1, T1),
                  card("m1", "medication.name", "Y", V1, T1)], {})
    with pytest.raises(ValueError, match="card_section"):
        der.plan([card("a1", "allergy.substance", "X", V1, T1, section="medication")], {})


def test_a_reviewed_at_without_timezone_is_refused():
    with pytest.raises(ValueError, match="timezone"):
        der.plan([card("a1", "allergy.substance", "X", V1, "2026-11-22T09:00:00")], {})


# ------------------------------------------------------- through the real CLI

def test_cli_retires_the_removed_entry_and_the_summary_no_longer_shows_it(client, db, tmp_path):
    pg = str(_patient(db).guid)
    v1 = [card("a1", "allergy.substance", "Penicillin", V1, T1, patient=pg, group="x"),
          card("a2", "allergy.substance", "Nötter", V1, T1, patient=pg, group="y")]
    assert _cli(client, _export(tmp_path, v1), "--apply", "--expect", "2").exit_code == 0
    path = _export(tmp_path, v1 + [card("b1", "allergy.substance", "Penicillin", V2, T2,
                                        patient=pg, group="x")])
    dry = _cli(client, path)
    assert "planned {'create': 1, 'retire': 2}" in dry.output, dry.output
    res = _cli(client, path, "--apply", "--expect", "3")
    assert res.exit_code == 0, res.output
    assert [r.resource_json["code"]["text"] for r in _derived(db)] == ["Penicillin"]
    tombs = db.session.query(FhirResource).filter_by(status="retired").all()
    assert sorted(t.resource_id for t in tombs) == sorted(
        [der.eps_id_for("a1"), der.eps_id_for("a2")])
    assert all(t.version_id == 2 for t in tombs), "history kept: v1 superseded, v2 retired"
    body = client.get(f"/api/v1/patients/{pg}/euips-summary").get_json()
    allergies = next(s for s in body["sections"] if s["key"] == "allergies")
    assert [e["display"] for e in allergies["entries"]] == ["Penicillin"]
    again = _cli(client, path, "--apply", "--expect", "0")
    assert again.exit_code == 0, again.output
    stale = _cli(client, _export(tmp_path, v1), "--apply")
    assert stale.exit_code != 0 and "older than the EPS" in stale.output
    assert len(_derived(db)) == 1
