"""FHIR REST surface — /fhir/... endpoints (FHIR R5)."""

import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.models.base import db
from app.models.patient_index import PatientIndex
from app.models.capability_statement import CapabilityStatement
from app.services.auth_service import require_auth
from app.services.audit_service import log_event
from app.services.fhir_service import (
    SUPPORTED_RESOURCE_TYPES,
    create_resource,
    update_resource,
    read_resource,
    search_resources,
    search_patients,
)
from app.services.ips_generator import generate_ips_bundle

bp = Blueprint("fhir_api", __name__, url_prefix="/fhir")


# Ticket #349 §3.1 — CapabilityStatement.date via file mtime. Stable across
# gunicorn workers (default fork model would make datetime.now() drift per
# worker; memory `infra_gunicorn_worker_fork_freezes_datetime`) AND stable
# across requests. Only advances on a real image rebuild.
_CAPABILITYSTATEMENT_DATE = datetime.fromtimestamp(
    os.path.getmtime(__file__), tz=timezone.utc
).strftime("%Y-%m-%dT%H:%M:%SZ")


def _operation_outcome(severity: str, code: str, diagnostics: str, status: int = 400):
    """Return a FHIR OperationOutcome response."""
    return jsonify({
        "resourceType": "OperationOutcome",
        "issue": [{
            "severity": severity,
            "code": code,
            "diagnostics": diagnostics,
        }]
    }), status


# ── Capability Statement ─────────────────────────────────────

@bp.route("/metadata", methods=["GET"])
def capability_statement():
    """Return the FHIR CapabilityStatement."""
    cs = db.session.query(CapabilityStatement).filter_by(is_current=True).first()
    if cs:
        return jsonify(cs.resource_json)
    return jsonify(_default_capability_statement())


# ── Patient CRUD ─────────────────────────────────────────────

@bp.route("/Patient", methods=["POST"])
@require_auth
def create_patient():
    data = request.get_json(silent=True) or {}
    if data.get("resourceType") != "Patient":
        return _operation_outcome("error", "invalid", "resourceType must be Patient")

    fhir_res = create_resource("Patient", data)
    log_event("fhir_create", resource_type="Patient", resource_guid=fhir_res.guid)
    db.session.commit()
    return jsonify(fhir_res.resource_json), 201


@bp.route("/Patient/<resource_id>", methods=["GET"])
@require_auth
def read_patient(resource_id):
    fhir_res = read_resource("Patient", resource_id)
    if not fhir_res:
        return _operation_outcome("error", "not-found", f"Patient/{resource_id} not found", 404)
    return jsonify(fhir_res.resource_json)


@bp.route("/Patient/<resource_id>", methods=["PUT"])
@require_auth
def update_patient(resource_id):
    data = request.get_json(silent=True) or {}
    if data.get("resourceType") != "Patient":
        return _operation_outcome("error", "invalid", "resourceType must be Patient")

    fhir_res = update_resource("Patient", resource_id, data)
    if not fhir_res:
        return _operation_outcome("error", "not-found", f"Patient/{resource_id} not found", 404)

    log_event("fhir_update", resource_type="Patient", resource_guid=fhir_res.guid)
    db.session.commit()
    return jsonify(fhir_res.resource_json)


@bp.route("/Patient", methods=["GET"])
@require_auth
def search_patient():
    """Search patients by identifier, family, given, birthdate."""
    patients = search_patients(
        identifier=request.args.get("identifier"),
        family=request.args.get("family"),
        given=request.args.get("given"),
        birthdate=request.args.get("birthdate"),
    )

    # Return as FHIR Bundle searchset
    entries = []
    for pi in patients:
        fhir_res = read_resource("Patient", pi.resource_id)
        if fhir_res:
            entries.append({
                "fullUrl": f"Patient/{pi.resource_id}",
                "resource": fhir_res.resource_json,
            })

    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": entries,
    }
    return jsonify(bundle)


# ── $ips Operation ───────────────────────────────────────────

@bp.route("/Patient/<resource_id>/$ips", methods=["GET"])
@require_auth
def ips_operation(resource_id):
    """Generate IPS Bundle for a patient (FHIR $ips operation)."""
    pi = db.session.query(PatientIndex).filter_by(resource_id=resource_id).first()
    if not pi:
        return _operation_outcome("error", "not-found", f"Patient/{resource_id} not found", 404)

    mode = request.args.get("mode", "full")
    bundle = generate_ips_bundle(pi, mode=mode)
    log_event("ips_generate", patient_guid=pi.guid, detail={"mode": mode})
    db.session.commit()
    return jsonify(bundle)


# ── Generic Clinical Resource CRUD ───────────────────────────

@bp.route("/<resource_type>", methods=["POST"])
@require_auth
def create_clinical_resource(resource_type):
    if resource_type not in SUPPORTED_RESOURCE_TYPES or resource_type == "Patient":
        return _operation_outcome("error", "not-supported", f"{resource_type} is not supported")

    data = request.get_json(silent=True) or {}
    if data.get("resourceType") != resource_type:
        return _operation_outcome("error", "invalid", f"resourceType must be {resource_type}")

    # Determine patient linkage
    patient_guid = None
    subject = data.get("subject", {})
    subject_ref = subject.get("reference", "") if isinstance(subject, dict) else ""
    if subject_ref.startswith("Patient/"):
        patient_id = subject_ref.split("/", 1)[1]
        pi = db.session.query(PatientIndex).filter_by(resource_id=patient_id).first()
        if pi:
            patient_guid = pi.guid

    # Also check patient field (some resource types use 'patient' instead of 'subject')
    if not patient_guid:
        patient_field = data.get("patient", {})
        patient_ref = patient_field.get("reference", "") if isinstance(patient_field, dict) else ""
        if patient_ref.startswith("Patient/"):
            patient_id = patient_ref.split("/", 1)[1]
            pi = db.session.query(PatientIndex).filter_by(resource_id=patient_id).first()
            if pi:
                patient_guid = pi.guid

    fhir_res = create_resource(resource_type, data, patient_guid=patient_guid)
    log_event("fhir_create", resource_type=resource_type, resource_guid=fhir_res.guid)
    db.session.commit()
    return jsonify(fhir_res.resource_json), 201


@bp.route("/<resource_type>/<resource_id>", methods=["GET"])
@require_auth
def read_clinical_resource(resource_type, resource_id):
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        return _operation_outcome("error", "not-supported", f"{resource_type} is not supported")

    fhir_res = read_resource(resource_type, resource_id)
    if not fhir_res:
        return _operation_outcome("error", "not-found", f"{resource_type}/{resource_id} not found", 404)
    return jsonify(fhir_res.resource_json)


@bp.route("/<resource_type>", methods=["GET"])
@require_auth
def search_clinical_resource(resource_type):
    if resource_type not in SUPPORTED_RESOURCE_TYPES or resource_type == "Patient":
        return _operation_outcome("error", "not-supported", f"{resource_type} search not supported here")

    results = search_resources(
        resource_type,
        patient_id=request.args.get("patient"),
    )

    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(results),
        "entry": [
            {"fullUrl": f"{r.resource_type}/{r.resource_id}", "resource": r.resource_json}
            for r in results
        ],
    }
    return jsonify(bundle)


# ── Default Capability Statement ─────────────────────────────

def _default_capability_statement() -> dict:
    """Generate a default CapabilityStatement for FHIR R5."""
    resources = []
    for rt in SUPPORTED_RESOURCE_TYPES:
        interaction = [{"code": "read"}, {"code": "search-type"}]
        if rt == "Patient":
            interaction.extend([{"code": "create"}, {"code": "update"}])
        else:
            interaction.append({"code": "create"})

        resource_entry = {
            "type": rt,
            "interaction": interaction,
        }

        if rt == "Patient":
            resource_entry["searchParam"] = [
                {"name": "identifier", "type": "token"},
                {"name": "family", "type": "string"},
                {"name": "given", "type": "string"},
                {"name": "birthdate", "type": "date"},
            ]
            resource_entry["operation"] = [{
                "name": "ips",
                "definition": "http://hl7.org/fhir/uv/ips/OperationDefinition/summary",
            }]
        else:
            resource_entry["searchParam"] = [
                {"name": "patient", "type": "reference"},
            ]

        resources.append(resource_entry)

    return {
        "resourceType": "CapabilityStatement",
        "id": "ips-pdhc",
        "url": "https://ips.pdhc.se/fhir/metadata",
        "version": "1.0.0",
        "name": "IpsPDHCCapabilityStatement",
        "title": "ips.pdhc — PDHC patient registry (FHIR R5)",
        "status": "active",
        # Ticket #349 §3.1 — see _CAPABILITYSTATEMENT_DATE definition
        # at top of module for the mtime rationale.
        "date": _CAPABILITYSTATEMENT_DATE,
        "publisher": "PDHC",
        "description": (
            "PDHC patient-registry FHIR R5 service. Stores Patient plus "
            "the IPS clinical resources (Condition, Observation, "
            "MedicationStatement, AllergyIntolerance, Immunization, "
            "Procedure, DocumentReference), implements $ips per HL7 uv/ips, "
            "and owns per-clinic org-scoping + PDL block/consent (spärr). "
            "See ips.pdhc/description_of_IPS.md for the full contract."
        ),
        "kind": "instance",
        # cpb-14: kind=instance requires implementation. Added in
        # #349 §3.3 as part of the R5 validator baseline.
        "implementation": {
            "description": "ips.pdhc production instance",
            "url": "https://ips.pdhc.se",
        },
        "fhirVersion": "5.0.0",
        "format": ["json"],
        "rest": [{
            "mode": "server",
            "resource": resources,
        }],
    }
