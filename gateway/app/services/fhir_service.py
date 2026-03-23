"""FHIR resource storage service."""

import uuid
from datetime import date

from sqlalchemy import and_

from app.models.base import db, utcnow
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex


SUPPORTED_RESOURCE_TYPES = [
    "Patient",
    "Condition",
    "Observation",
    "MedicationStatement",
    "AllergyIntolerance",
    "Immunization",
    "Procedure",
    "DocumentReference",
    "DiagnosticReport",
]


def create_resource(resource_type: str, resource_json: dict, patient_guid: uuid.UUID | None = None) -> FhirResource:
    """Store a new FHIR resource."""
    resource_id = resource_json.get("id") or str(uuid.uuid4())
    resource_json["id"] = resource_id

    fhir_res = FhirResource(
        resource_type=resource_type,
        resource_id=resource_id,
        version_id=1,
        resource_json=resource_json,
        patient_guid=patient_guid,
        status="active",
    )
    db.session.add(fhir_res)
    db.session.flush()

    # If Patient, sync patient_index
    if resource_type == "Patient":
        _sync_patient_index(fhir_res)

    return fhir_res


def update_resource(resource_type: str, resource_id: str, resource_json: dict) -> FhirResource | None:
    """Update a FHIR resource by creating a new version."""
    current = db.session.query(FhirResource).filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
        status="active",
    ).order_by(FhirResource.version_id.desc()).first()

    if not current:
        return None

    resource_json["id"] = resource_id
    new_version = FhirResource(
        resource_type=resource_type,
        resource_id=resource_id,
        version_id=current.version_id + 1,
        resource_json=resource_json,
        patient_guid=current.patient_guid,
        status="active",
    )
    current.status = "superseded"
    db.session.add(new_version)
    db.session.flush()

    if resource_type == "Patient":
        _sync_patient_index(new_version)

    return new_version


def read_resource(resource_type: str, resource_id: str) -> FhirResource | None:
    """Read the current version of a FHIR resource."""
    return db.session.query(FhirResource).filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
        status="active",
    ).order_by(FhirResource.version_id.desc()).first()


def search_resources(
    resource_type: str,
    patient_id: str | None = None,
    **kwargs,
) -> list[FhirResource]:
    """Search for FHIR resources with basic filters."""
    query = db.session.query(FhirResource).filter_by(
        resource_type=resource_type,
        status="active",
    )

    if patient_id:
        # Look up patient_guid from patient_index
        pi = db.session.query(PatientIndex).filter_by(resource_id=patient_id).first()
        if pi:
            query = query.filter(FhirResource.patient_guid == pi.guid)
        else:
            return []

    return query.order_by(FhirResource.last_updated.desc()).all()


def search_patients(
    identifier: str | None = None,
    family: str | None = None,
    given: str | None = None,
    birthdate: str | None = None,
) -> list[PatientIndex]:
    """Search patient index."""
    query = db.session.query(PatientIndex).filter_by(is_active=True)

    if identifier:
        query = query.filter(PatientIndex.identifier_value == identifier)
    if family:
        query = query.filter(PatientIndex.family_name.ilike(f"%{family}%"))
    if given:
        query = query.filter(PatientIndex.given_name.ilike(f"%{given}%"))
    if birthdate:
        try:
            bd = date.fromisoformat(birthdate)
            query = query.filter(PatientIndex.birth_date == bd)
        except ValueError:
            pass

    return query.order_by(PatientIndex.family_name).all()


def _sync_patient_index(fhir_res: FhirResource) -> None:
    """Sync patient_index from a Patient FHIR resource."""
    rjson = fhir_res.resource_json

    # Extract searchable fields
    family_name = None
    given_name = None
    names = rjson.get("name", [])
    if names:
        family_name = names[0].get("family")
        givens = names[0].get("given", [])
        given_name = " ".join(givens) if givens else None

    identifier_system = None
    identifier_value = None
    identifiers = rjson.get("identifier", [])
    if identifiers:
        identifier_system = identifiers[0].get("system")
        identifier_value = identifiers[0].get("value")

    birth_date = None
    bd_str = rjson.get("birthDate")
    if bd_str:
        try:
            birth_date = date.fromisoformat(bd_str)
        except ValueError:
            pass

    gender = rjson.get("gender")

    # Update or create index entry
    existing = db.session.query(PatientIndex).filter_by(
        resource_id=fhir_res.resource_id
    ).first()

    if existing:
        existing.fhir_resource_guid = fhir_res.guid
        existing.identifier_system = identifier_system
        existing.identifier_value = identifier_value
        existing.family_name = family_name
        existing.given_name = given_name
        existing.birth_date = birth_date
        existing.gender = gender
        existing.updated_at = utcnow()
    else:
        pi = PatientIndex(
            fhir_resource_guid=fhir_res.guid,
            resource_id=fhir_res.resource_id,
            identifier_system=identifier_system,
            identifier_value=identifier_value,
            family_name=family_name,
            given_name=given_name,
            birth_date=birth_date,
            gender=gender,
        )
        db.session.add(pi)
        # Also set patient_guid on the FhirResource
        db.session.flush()
        fhir_res.patient_guid = pi.guid

    db.session.flush()
