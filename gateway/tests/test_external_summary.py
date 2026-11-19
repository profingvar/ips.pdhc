"""POST /api/v1/patients/external-summary -- the de-identified IPS summary an
external read grant may see, fetched by the CDRs (2026-11-19)."""
import json
import uuid
from datetime import date
from unittest.mock import patch

from app.models.api_key import ApiKey
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services.auth_service import SCOPE_EXTERNAL_SUMMARY, hash_api_key

URL = "/api/v1/patients/external-summary"
PNR = "19121212-1212"


def _key(db, scopes):
    raw = f"k-{uuid.uuid4()}"
    db.session.add(ApiKey(key_hash=hash_api_key(raw), label="ext test",
                          prefix=raw[:8], scopes=scopes, is_active=True))
    db.session.commit()
    return {"Authorization": f"ApiKey {raw}"}


def _patient(db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid, resource_id=str(uuid.uuid4()),
                     identifier_system="http://electronichealth.se/identifier/personnummer",
                     identifier_value=PNR, family_name="Hemligsson",
                     given_name="Greta", birth_date=date(1961, 5, 17), gender="female")
    db.session.add(p)
    db.session.flush()
    db.session.add(FhirResource(
        resource_type="Condition", resource_id=str(uuid.uuid4()), patient_guid=p.guid,
        resource_json={"resourceType": "Condition",
                       "code": {"coding": [{"system": "http://id.who.int/icd/release/11/mms",
                                            "code": "5A11", "display": "Type 2 diabetes"}],
                                "text": "fritext om Greta"},
                       "clinicalStatus": {"coding": [{"code": "active"}]},
                       "onsetDateTime": "2019-03-01",
                       "note": [{"text": "ringde Greta Hemligsson"}]}))
    db.session.add(FhirResource(
        resource_type="Condition", resource_id=str(uuid.uuid4()), patient_guid=p.guid,
        resource_json={"resourceType": "Condition",
                       "code": {"coding": [{"code": "XX"}]},
                       "verificationStatus": {"coding": [{"code": "entered-in-error"}]}}))
    db.session.add(FhirResource(
        resource_type="MedicationStatement", resource_id=str(uuid.uuid4()), patient_guid=p.guid,
        resource_json={"resourceType": "MedicationStatement", "status": "active",
                       "medication": {"concept": {"coding": [
                           {"system": "http://www.whocc.no/atc", "code": "A10BA02",
                            "display": "metformin"}]}},
                       "effectivePeriod": {"start": "2019-04-01"}}))
    db.session.commit()
    return str(p.guid)


def _post(client, headers, body):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
        return client.post(URL, data=json.dumps(body), headers={
            **headers, "Content-Type": "application/json"})


def test_returns_only_the_permitted_fields(client, db):
    g = _patient(db)
    r = _post(client, _key(db, [SCOPE_EXTERNAL_SUMMARY]), {"patient_guids": [g]})
    assert r.status_code == 200, r.get_data(as_text=True)
    [p] = r.get_json()["patients"]
    assert set(p) == {"patient_guid", "sex", "birth_year", "conditions", "medications"}
    assert (p["patient_guid"], p["sex"], p["birth_year"]) == (g, "female", 1961)
    assert [c["code"][0]["code"] for c in p["conditions"]] == ["5A11"]   # error row dropped
    assert p["conditions"][0]["clinical_status"] == "active"
    assert p["medications"][0]["code"][0]["code"] == "A10BA02"
    text = r.get_data(as_text=True)
    for leak in (PNR, "Hemligsson", "Greta", "1961-05-17", "fritext", "ringde"):
        assert leak not in text, leak


def test_needs_the_scope(client, db):
    g = _patient(db)
    assert _post(client, _key(db, ["consent:read"]), {"patient_guids": [g]}).status_code == 403
    assert _post(client, {}, {"patient_guids": [g]}).status_code == 401


def test_unknown_patients_are_left_out_and_bad_input_refused(client, db):
    h = _key(db, [SCOPE_EXTERNAL_SUMMARY])
    assert _post(client, h, {"patient_guids": [str(uuid.uuid4())]}).get_json() == {"patients": []}
    assert _post(client, h, {"patient_guids": []}).status_code == 400
    assert _post(client, h, {"patient_guids": ["not-a-uuid"]}).status_code == 400
    assert _post(client, h, {"patient_guids": [str(uuid.uuid4())] * 1001}).status_code == 400
