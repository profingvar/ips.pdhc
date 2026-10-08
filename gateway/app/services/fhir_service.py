"""FHIR resource storage service."""

import uuid

from flask import current_app
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


def _as_uuid_or_none(value):
    """`value` as a UUID, or None when it is not one.

    Exists so `PatientIndex.guid` (a UUID column) is never handed a non-UUID
    string, which would raise at the driver and surface as a 500 — the #805
    shape.
    """
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


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
        # ── ONE identifier per patient (operator principle, 2026-10-08) ──
        #
        # "Patient information must be reachable by THE guid wherever it is in
        # the platform, and a guid must have a 1:1 relation to a personnummer,
        # a caregiver and a careunit."
        #
        # This minted TWO independent uuid4s for one person: `guid` took the
        # column default while `resource_id` came from the FHIR resource. They
        # were never equal, so a patient was reachable by one value here and a
        # different value there — `/fhir/Patient/<a>` vs
        # `/api/v1/patients/<b>/clinics`. Measured 2026-10-08: 150 of 150
        # patients carried two different ids, and request.pdhc's 27
        # ServiceRequests all stored the FHIR one while cdr and #782 use the
        # platform one.
        #
        # `PatientIndex.guid` is canonical — #782, the CDRs and ips's own
        # technical manual all call it the platform identifier — so the FHIR
        # resource id is made EQUAL to it rather than the other way round. A
        # FHIR resource id is free-form by spec, so this is the side with room
        # to give.
        _pi_guid = _as_uuid_or_none(fhir_res.resource_id)
        if _pi_guid is None:
            # A caller supplied a resource id that is not a UUID. The columns
            # cannot be unified, so this patient WILL carry two identifiers.
            # Logged rather than silently tolerated: it is a conformance
            # breach, and `tools/` can count it.
            current_app.logger.warning(
                "patient resource_id %r is not a UUID, so PatientIndex.guid "
                "cannot equal it — this patient will carry TWO identifiers, "
                "breaking the one-guid principle",
                fhir_res.resource_id)
        pi = PatientIndex(
            **({"guid": _pi_guid} if _pi_guid else {}),
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
