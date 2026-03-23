"""IPS Bundle generation service — FHIR R5 compliant."""

import uuid
from datetime import datetime, timezone

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex


# Resource types included in a full IPS
FULL_IPS_TYPES = [
    "Condition",
    "Observation",
    "MedicationStatement",
    "AllergyIntolerance",
    "Immunization",
    "Procedure",
    "DocumentReference",
    "DiagnosticReport",
]

# Resource types included in a minimal IPS
MINIMAL_IPS_TYPES = [
    "Condition",
    "MedicationStatement",
    "AllergyIntolerance",
]

IPS_PROFILE_URL = "http://hl7.org/fhir/uv/ips/StructureDefinition/Bundle-uv-ips"


def generate_ips_bundle(
    patient_index: PatientIndex,
    mode: str = "full",
    composition_date: datetime | None = None,
) -> dict:
    """Generate an IPS document Bundle for a patient.

    Args:
        patient_index: The patient to generate for.
        mode: 'full' or 'minimal'.
        composition_date: The 'as of' date. Defaults to now.

    Returns:
        A FHIR R5 Bundle resource dict.
    """
    if composition_date is None:
        composition_date = datetime.now(timezone.utc)

    resource_types = FULL_IPS_TYPES if mode == "full" else MINIMAL_IPS_TYPES

    # Fetch the Patient resource
    patient_resource = db.session.query(FhirResource).filter_by(
        resource_type="Patient",
        resource_id=patient_index.resource_id,
        status="active",
    ).order_by(FhirResource.version_id.desc()).first()

    if not patient_resource:
        return _empty_ips_bundle(patient_index, composition_date)

    # Fetch clinical resources for this patient
    clinical_resources = db.session.query(FhirResource).filter(
        FhirResource.patient_guid == patient_index.guid,
        FhirResource.resource_type.in_(resource_types),
        FhirResource.status == "active",
    ).all()

    # Build bundle entries
    entries = []
    section_entries_by_type: dict[str, list] = {}

    # Patient entry
    patient_fullurl = f"urn:uuid:{patient_resource.resource_id}"
    entries.append({
        "fullUrl": patient_fullurl,
        "resource": patient_resource.resource_json,
    })

    # Clinical resource entries
    for res in clinical_resources:
        fullurl = f"urn:uuid:{res.resource_id}"
        entries.append({
            "fullUrl": fullurl,
            "resource": res.resource_json,
        })
        section_entries_by_type.setdefault(res.resource_type, []).append({
            "reference": fullurl,
        })

    # Build Composition
    composition_id = str(uuid.uuid4())
    composition_fullurl = f"urn:uuid:{composition_id}"

    sections = _build_sections(section_entries_by_type, resource_types)

    composition = {
        "resourceType": "Composition",
        "id": composition_id,
        "status": "final",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "60591-5",
                "display": "Patient summary Document",
            }]
        },
        "subject": {"reference": patient_fullurl},
        "date": composition_date.isoformat(),
        "title": "International Patient Summary",
        "section": sections,
    }

    entries.insert(0, {
        "fullUrl": composition_fullurl,
        "resource": composition,
    })

    # Assemble Bundle
    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {
            "profile": [IPS_PROFILE_URL],
        },
        "type": "document",
        "timestamp": composition_date.isoformat(),
        "entry": entries,
    }

    return bundle


def _build_sections(
    entries_by_type: dict[str, list],
    resource_types: list[str],
) -> list[dict]:
    """Build IPS Composition sections from grouped resource entries."""
    section_map = {
        "Condition": {
            "title": "Active Problems",
            "code": {"coding": [{"system": "http://loinc.org", "code": "11450-4", "display": "Problem list"}]},
        },
        "MedicationStatement": {
            "title": "Medication Summary",
            "code": {"coding": [{"system": "http://loinc.org", "code": "10160-0", "display": "Medication use"}]},
        },
        "AllergyIntolerance": {
            "title": "Allergies and Intolerances",
            "code": {"coding": [{"system": "http://loinc.org", "code": "48765-2", "display": "Allergies"}]},
        },
        "Immunization": {
            "title": "Immunizations",
            "code": {"coding": [{"system": "http://loinc.org", "code": "11369-6", "display": "Immunizations"}]},
        },
        "Observation": {
            "title": "Results",
            "code": {"coding": [{"system": "http://loinc.org", "code": "30954-2", "display": "Results"}]},
        },
        "Procedure": {
            "title": "Procedures",
            "code": {"coding": [{"system": "http://loinc.org", "code": "47519-4", "display": "Procedures"}]},
        },
        "DocumentReference": {
            "title": "Advance Directives",
            "code": {"coding": [{"system": "http://loinc.org", "code": "42348-3", "display": "Advance directives"}]},
        },
        "DiagnosticReport": {
            "title": "Diagnostic Results",
            "code": {"coding": [{"system": "http://loinc.org", "code": "30954-2", "display": "Diagnostic results"}]},
        },
    }

    sections = []
    for rtype in resource_types:
        meta = section_map.get(rtype)
        if not meta:
            continue
        entries = entries_by_type.get(rtype, [])
        section = {
            "title": meta["title"],
            "code": meta["code"],
        }
        if entries:
            section["entry"] = entries
        else:
            # IPS requires emptyReason when no data
            section["emptyReason"] = {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/list-empty-reason",
                    "code": "unavailable",
                    "display": "Unavailable",
                }]
            }
        sections.append(section)
    return sections


def _empty_ips_bundle(patient_index: PatientIndex, composition_date: datetime) -> dict:
    """Generate a minimal IPS bundle when no Patient resource exists."""
    bundle_id = str(uuid.uuid4())
    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {"profile": [IPS_PROFILE_URL]},
        "type": "document",
        "timestamp": composition_date.isoformat(),
        "entry": [],
    }
