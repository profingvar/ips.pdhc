"""#980 — the live euIPS summary: status AND entries per section.

Reuses euips_sections' own classification, so the test this file exists for
is `test_the_summary_and_the_status_route_NEVER_disagree`.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.audit_log import AuditLog
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_sections as euips
from app.services import euips_summary as summ

ABSENT = "http://hl7.org/fhir/uv/ips/CodeSystem/absent-unknown-uv-ips"
SNOMED = "http://snomed.info/sct"


def _patient(db):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res); db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     family_name="Summary", given_name="Test")
    db.session.add(p); db.session.commit()
    res.patient_guid = p.guid; db.session.commit()
    return p


def _add(db, patient, rtype, body):
    rid = str(uuid.uuid4())
    body = {"resourceType": rtype, "id": rid, **body}
    r = FhirResource(resource_type=rtype, resource_id=rid,
                     resource_json=body, patient_guid=patient.guid)
    db.session.add(r); db.session.commit()
    return r


def _allergy(code="91936005", display="Penicillin allergy"):
    return {"code": {"coding": [{"system": SNOMED, "code": code, "display": display}]},
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "recordedDate": "2025-03-01",
            "text": {"status": "generated",
                     "div": "<div xmlns='http://www.w3.org/1999/xhtml'><b>Penicillin</b> allergy</div>"}}


def _absent(section_key):
    """The REAL absent assertion, built by the module that defines it —
    `absent_coding` returns a whole CodeableConcept."""
    return {"code": euips.absent_coding(section_key),
            "text": {"status": "generated",
                     "div": "<div xmlns='http://www.w3.org/1999/xhtml'>No known allergies</div>"}}


def _section(sections, key):
    return next(s for s in sections if s["key"] == key)


def _rows(db, p):
    return db.session.query(FhirResource).filter_by(patient_guid=p.guid).all()


# --------------------------------------------------------------------------
# the three states, inherited
# --------------------------------------------------------------------------

def test_a_real_allergy_is_PRESENT_with_its_entry(db):
    p = _patient(db); _add(db, p, "AllergyIntolerance", _allergy())
    s = _section(summ.compose(_rows(db, p)), "allergies")
    assert s["status"] == euips.PRESENT
    e = s["entries"][0]
    assert e["display"] == "Penicillin allergy"
    assert e["code"] == "91936005" and e["system"] == SNOMED
    assert e["status"] == "active" and e["date"] == "2025-03-01"
    assert e["source"] == "ips"


def test_an_absent_assertion_is_EXPLICITLY_ABSENT_and_carries_its_text(db):
    p = _patient(db)
    _add(db, p, "AllergyIntolerance", _absent("allergies"))
    s = _section(summ.compose(_rows(db, p)), "allergies")
    assert s["status"] == euips.EXPLICITLY_ABSENT
    assert s["entries"] == []
    assert s["absent"]["narrative_text"] == "No known allergies"


def test_real_content_WINS_over_a_stale_absent_assertion(db):
    p = _patient(db)
    _add(db, p, "AllergyIntolerance", _absent("allergies"))
    _add(db, p, "AllergyIntolerance", _allergy())
    s = _section(summ.compose(_rows(db, p)), "allergies")
    assert s["status"] == euips.PRESENT
    assert s["absent"] is None, "a stale assertion must not sit beside the data"
    assert len(s["entries"]) == 1


def test_nothing_at_all_is_MISSING_not_absent(db):
    """The distinction #791 exists for: "nothing recorded" is not "the
    clinician recorded nothing to report"."""
    p = _patient(db)
    s = _section(summ.compose(_rows(db, p)), "allergies")
    assert s["status"] == euips.MISSING
    assert s["entries"] == [] and s["absent"] is None


def test_the_summary_and_the_status_route_NEVER_disagree(db):
    """Both are derived from the same rows by the same classifier. If they
    ever disagreed, a consumer showing the summary and a consumer checking
    conformance would describe two different patients."""
    p = _patient(db)
    _add(db, p, "AllergyIntolerance", _allergy())
    _add(db, p, "Condition", {"code": {"coding": [{"system": SNOMED, "code": "73211009",
                                                    "display": "Diabetes"}]},
                              "clinicalStatus": {"coding": [{"code": "active"}]}})
    _add(db, p, "Immunization", {"vaccineCode": {"coding": [{"code": "x", "display": "Flu"}]},
                                 "status": "completed"})
    rows = _rows(db, p)
    status = euips.status_for_resources(rows)
    for s in summ.compose(rows):
        assert s["status"] == status[s["key"]], s["key"]
        if s["status"] != euips.PRESENT:
            assert s["entries"] == [], s["key"]


# --------------------------------------------------------------------------
# classification is DISCRIMINATING, because Condition is shared by three
# --------------------------------------------------------------------------

def test_an_active_condition_is_a_PROBLEM_and_a_resolved_one_is_NOT(db):
    p = _patient(db)
    _add(db, p, "Condition", {"code": {"coding": [{"code": "1", "display": "Active one"}]},
                              "clinicalStatus": {"coding": [{"code": "active"}]}})
    _add(db, p, "Condition", {"code": {"coding": [{"code": "2", "display": "Resolved one"}]},
                              "clinicalStatus": {"coding": [{"code": "resolved"}]}})
    secs = summ.compose(_rows(db, p))
    problems = [e["display"] for e in _section(secs, "problems")["entries"]]
    past = [e["display"] for e in _section(secs, "past_illnesses")["entries"]]
    assert problems == ["Active one"]
    assert "Resolved one" in past
    assert "Resolved one" not in problems


# --------------------------------------------------------------------------
# entries
# --------------------------------------------------------------------------

def test_duplicates_are_NOT_collapsed(db):
    """Production holds one patient with the same Condition twice (#984).
    Hiding that here would bury a data defect in a presentation layer."""
    p = _patient(db)
    for _ in range(2):
        _add(db, p, "Condition", {"code": {"coding": [{"code": "49436004",
                                                        "display": "Atrial fibrillation"}]},
                                  "clinicalStatus": {"coding": [{"code": "active"}]}})
    assert len(_section(summ.compose(_rows(db, p)), "problems")["entries"]) == 2


def test_the_narrative_is_returned_as_PLAIN_TEXT():
    """A consumer rendering the XHTML div would render markup it did not
    write."""
    assert summ.narrative_text({"text": {"div": "<div><b>Penicillin</b> allergy</div>"}}) \
        == "Penicillin allergy"


def test_an_R5_medication_reference_is_read(db):
    p = _patient(db)
    _add(db, p, "MedicationStatement", {
        "medication": {"concept": {"coding": [{"code": "N02BE01", "display": "Paracetamol"}]}},
        "status": "recorded"})
    e = _section(summ.compose(_rows(db, p)), "medications")["entries"][0]
    assert e["display"] == "Paracetamol" and e["code"] == "N02BE01"


def test_an_observation_carries_its_value_and_unit(db):
    p = _patient(db)
    _add(db, p, "Observation", {
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "code": {"coding": [{"code": "29463-7", "display": "Body weight"}]},
        "valueQuantity": {"value": 72.5, "unit": "kg"},
        "effectiveDateTime": "2026-01-01"})
    e = _section(summ.compose(_rows(db, p)), "vital_signs")["entries"][0]
    assert e["value"] == 72.5 and e["unit"] == "kg"


# --------------------------------------------------------------------------
# the route
# --------------------------------------------------------------------------

def test_the_route_returns_sections_with_entries_and_its_source(client, db):
    p = _patient(db); _add(db, p, "AllergyIntolerance", _allergy())
    r = client.get(f"/api/v1/patients/{p.guid}/euips-summary")
    assert r.status_code == 200
    body = r.get_json()
    assert body["source"] == "ips"
    assert len(body["sections"]) == len(euips.SECTIONS)
    assert _section(body["sections"], "allergies")["entries"][0]["display"] == "Penicillin allergy"
    assert "eps" in body["conformance"]


def test_the_read_is_AUDITED(client, db):
    p = _patient(db); _add(db, p, "AllergyIntolerance", _allergy())
    client.get(f"/api/v1/patients/{p.guid}/euips-summary")
    rows = db.session.query(AuditLog).filter_by(event_type="euips_summary_read").all()
    assert rows, "a read of clinical content left no audit trail"
    assert str(rows[-1].patient_guid) == str(p.guid)


def test_an_unknown_and_an_out_of_scope_patient_get_the_SAME_404(client, db, monkeypatch):
    p = _patient(db)
    from app.services import patient_export as px
    monkeypatch.setattr(px, "exportable", lambda guids: ([], []))
    hidden = client.get(f"/api/v1/patients/{p.guid}/euips-summary")
    missing = client.get(f"/api/v1/patients/{uuid.uuid4()}/euips-summary")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.get_json() == missing.get_json()


def test_a_FAILING_scope_check_is_503_not_not_found(client, db, monkeypatch):
    """`/state` folds this into "not found". Here "could not check" is said
    as such."""
    p = _patient(db)
    from app.services import patient_export as px

    def boom(guids):
        raise RuntimeError("care_access unreachable")
    monkeypatch.setattr(px, "exportable", boom)
    r = client.get(f"/api/v1/patients/{p.guid}/euips-summary")
    assert r.status_code == 503
    assert r.get_json()["error"] == "scope_undetermined"
