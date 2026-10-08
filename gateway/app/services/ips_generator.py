"""IPS Bundle generation service — FHIR R5 compliant."""

import uuid
from datetime import datetime, timezone

from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import euips_header


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

# #792: document-HEADER resource types. They travel in the bundle as entries
# that the Composition header references, and they must NOT be fed to
# _build_sections -- they are not clinical sections, and a "Coverage section"
# would be a section the guideline does not define. Kept separate from
# FULL_IPS_TYPES for exactly that reason.
HEADER_TYPES = [
    "RelatedPerson",
    "Coverage",
]


def _custodian_clinic(patient_index: PatientIndex):
    """The clinic that is the document's custodian — #792.

    THE ASSIGNMENT IS AUTHORITATIVE. `PatientClinicAssignment` is what
    cross-service consumers query (`GET /api/v1/clinics/<guid>/patients` joins
    on this table, not on `managingOrganization`), so it is the fact; the
    Patient's `managingOrganization` and the Composition custodian are
    projections of it.

    This matters because #792's watch item is the #768 shape: three places
    holding one organisation. #768 is open precisely because three organisation
    identifiers on one datapoint did not collapse, and a Rule 24 gate ended up
    scoping on the wrong one. So the custodian is READ from the assignment
    rather than restated, and a disagreement is reported rather than resolved
    by preference.

    Returns the active assigned Clinic, or None. None is a correct answer: a
    patient with no assignment has no custodian, and inventing one would make
    the header contradict the assignment table.
    """
    return (db.session.query(Clinic)
            .join(PatientClinicAssignment,
                  PatientClinicAssignment.clinic_guid == Clinic.guid)
            .filter(PatientClinicAssignment.patient_guid == patient_index.guid)
            .filter(Clinic.is_active.is_(True))
            .order_by(Clinic.name)
            .first())


def custodian_disagreement(patient_json: dict, clinic) -> str | None:
    """Describe a custodian/managingOrganization mismatch, or None.

    Exposed rather than inlined so a report and a test can ask the same
    question the bundle builder asks. Returns a human sentence, because the
    only useful form of this finding is one an operator can read.
    """
    mo = (patient_json or {}).get("managingOrganization") or {}
    ref = (mo.get("reference") or "")
    mo_guid = ref.split("/")[-1] if "/" in ref else ""
    if clinic is None:
        return ("Patient names managingOrganization %s but has no active "
                "clinic assignment, so the summary has no custodian." % mo_guid
                ) if mo_guid else None
    assigned = str(clinic.organisation_guid or "")
    if mo_guid and assigned and mo_guid != assigned:
        return ("managingOrganization is %s but the authoritative assignment "
                "is %s (%s). The assignment wins; the Patient resource is "
                "stale." % (mo_guid, assigned, clinic.name))
    return None


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

    # #792: header resources, fetched SEPARATELY so they never reach
    # _build_sections. They belong to the document header, not to a clinical
    # section.
    header_resources = db.session.query(FhirResource).filter(
        FhirResource.patient_guid == patient_index.guid,
        FhirResource.resource_type.in_(HEADER_TYPES),
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

    # #792: header entries (RelatedPerson, Coverage). Added to the bundle but
    # deliberately NOT to section_entries_by_type.
    related_json = []
    coverage_json = []
    for res in header_resources:
        entries.append({
            "fullUrl": f"urn:uuid:{res.resource_id}",
            "resource": res.resource_json,
        })
        if res.resource_type == "RelatedPerson":
            related_json.append(res.resource_json)
        else:
            coverage_json.append(res.resource_json)

    # #792: the custodian organisation, derived from the AUTHORITATIVE clinic
    # assignment. See _custodian_clinic.
    clinic = _custodian_clinic(patient_index)
    org_json = euips_header.organization_resource(clinic)
    custodian_fullurl = None
    if org_json:
        custodian_fullurl = f"urn:uuid:{org_json['id']}"
        entries.append({"fullUrl": custodian_fullurl, "resource": org_json})

    # Build Composition
    composition_id = str(uuid.uuid4())
    composition_fullurl = f"urn:uuid:{composition_id}"

    sections = _build_sections(section_entries_by_type, resource_types)

    # Language comes from the Patient resource when it carries one, so the
    # document and the patient agree. A per-bundle random draw here would make
    # the same patient's summary change language between regenerations.
    patient_json = patient_resource.resource_json or {}
    language = _language_of(patient_json)

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
    composition.update(euips_header.composition_header(
        custodian_full_url=custodian_fullurl,
        custodian_display=clinic.name if clinic else None,
        language=language,
        attested_at=composition_date,
    ))

    # A stale managingOrganization is a real finding, not a thing to paper
    # over: the assignment is used regardless, and the disagreement is
    # recorded on the bundle so a reader can see the two did not match rather
    # than discovering it later from a wrongly scoped query (#768).
    disagreement = custodian_disagreement(patient_json, clinic)

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
    if disagreement:
        bundle["meta"]["tag"] = [{
            "system": "urn:pdhc:ips:warning",
            "code": "custodian-mismatch",
            "display": disagreement,
        }]

    return bundle


def _language_of(patient_json: dict) -> str:
    """The document language, taken from Patient.communication.

    Falls back to the Swedish default rather than drawing at random: a
    regenerated summary for the same patient must not change language, and a
    random draw here would do exactly that.
    """
    for c in (patient_json or {}).get("communication", ()):
        code = ((c.get("language") or {}).get("coding") or [{}])[0].get("code")
        if code:
            return code
    return "sv-SE"


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
