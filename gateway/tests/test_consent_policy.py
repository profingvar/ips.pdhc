"""#422 — canonical analysis consent policy + /analysis-filter endpoint.

Policy (evaluate_patient) is exhaustively unit-tested (the legal logic); the
endpoint is tested against seeded PatientIndex rows with the D1 flags set.
"""
import uuid

import pytest

from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services.consent_policy import evaluate_patient, EHDS_SECONDARY_PURPOSES


# --- policy unit tests ------------------------------------------------------

def test_no_flags_allows_non_research():
    assert evaluate_patient({}, "statistics") == (True, None)
    assert evaluate_patient({}, "care") == (True, None)


def test_ehds_opt_out_blocks_every_secondary_purpose():
    flags = {"ehds_opt_out": True}
    for p in EHDS_SECONDARY_PURPOSES:
        allowed, reason = evaluate_patient(flags, p, ["proj"])
        # research also needs consent, but ehds is checked first
        assert allowed is False
        assert reason in ("ehds_opt_out", "no_research_consent")
    # ehds opt-out does NOT block primary use
    assert evaluate_patient(flags, "care") == (True, None)
    assert evaluate_patient(flags, "patient_access") == (True, None)


def test_quality_registry_opt_out():
    flags = {"quality_registry_opt_out": True}
    assert evaluate_patient(flags, "quality_registry") == (False, "quality_registry_opt_out")
    # does not affect other purposes
    assert evaluate_patient(flags, "statistics") == (True, None)


def test_research_requires_project_consent_intersection():
    flags = {"consented_research_projects": ["projA", "projB"]}
    # reader works on projB -> overlap -> allowed
    assert evaluate_patient(flags, "research", ["projB", "projC"]) == (True, None)
    # reader works on projC only -> no overlap -> excluded
    assert evaluate_patient(flags, "research", ["projC"]) == (False, "no_research_consent")
    # no consent recorded -> excluded
    assert evaluate_patient({}, "research", ["projB"]) == (False, "no_research_consent")


def test_research_with_no_reader_projects_excluded():
    flags = {"consented_research_projects": ["projA"]}
    assert evaluate_patient(flags, "research", []) == (False, "no_research_consent")


# --- endpoint integration ---------------------------------------------------

@pytest.fixture
def two_patients(client, db):
    def _mk(**flags):
        fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                            resource_json={"resourceType": "Patient"})
        db.session.add(fhir)
        db.session.flush()
        p = PatientIndex(fhir_resource_guid=fhir.guid,
                         resource_id=str(uuid.uuid4()), **flags)
        db.session.add(p)
        db.session.flush()
        return str(p.guid)
    plain = _mk()
    ehds = _mk(ehds_opt_out=True)
    db.session.commit()
    return {"plain": plain, "ehds": ehds}


def test_analysis_filter_excludes_ehds_opt_out(client, two_patients):
    r = client.post("/api/v1/patients/analysis-filter", json={
        "patient_guids": [two_patients["plain"], two_patients["ehds"]],
        "purpose": "statistics",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["allowed"] == [two_patients["plain"]]
    assert body["excluded"] == [
        {"patient_guid": two_patients["ehds"], "reason": "ehds_opt_out"}]


def test_analysis_filter_requires_purpose(client):
    r = client.post("/api/v1/patients/analysis-filter",
                    json={"patient_guids": []})
    assert r.status_code == 400


def test_analysis_filter_research_needs_consent(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    proj = str(uuid.uuid4())
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     consented_research_projects=[proj])
    db.session.add(p)
    db.session.commit()
    guid = str(p.guid)

    ok = client.post("/api/v1/patients/analysis-filter", json={
        "patient_guids": [guid], "purpose": "research",
        "research_project_guids": [proj]})
    assert ok.get_json()["allowed"] == [guid]

    no = client.post("/api/v1/patients/analysis-filter", json={
        "patient_guids": [guid], "purpose": "research",
        "research_project_guids": [str(uuid.uuid4())]})
    assert no.get_json()["allowed"] == []
    assert no.get_json()["excluded"][0]["reason"] == "no_research_consent"
