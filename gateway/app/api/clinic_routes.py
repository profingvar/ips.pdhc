"""Clinic management routes."""

import uuid

from flask import Blueprint, current_app, jsonify, request

from app.models.base import db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services.auth_service import require_auth
from app.services.audit_service import log_event
from app.services.fhir_service import create_resource
from app.services import personnummer as pnr
from app.services.guids import is_uuid

bp = Blueprint("clinic_api", __name__, url_prefix="/api/v1/clinics")


@bp.route("", methods=["POST"])
@require_auth
def create_clinic():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    clinic = Clinic(
        name=data["name"],
        identifier=data.get("identifier"),
        organisation_guid=data.get("organisation_guid"),
    )
    db.session.add(clinic)
    log_event("clinic_create", resource_guid=clinic.guid)
    db.session.commit()
    return jsonify(clinic.to_dict()), 201


@bp.route("", methods=["GET"])
@require_auth
def list_clinics():
    clinics = db.session.query(Clinic).filter_by(is_active=True).order_by(Clinic.name).all()
    return jsonify([c.to_dict() for c in clinics])


@bp.route("/<guid>", methods=["GET"])
@require_auth
def get_clinic(guid):
    # #805: `Clinic.guid` is a real UUID column, so a non-UUID value RAISES
    # at the driver and Flask returns 500 — before the 404 below can run. The
    # 404 branch was unreachable for exactly the inputs it was written for.
    #
    # 400 rather than 404 on purpose: they are different answers. 404 says
    # "no such clinic", 400 says "that is not an identifier". A consumer
    # cannot tell a 500 from "the service is down" — which is how #730 became
    # a reported sibling outage — nor a 404 from "my input was rubbish".
    if not is_uuid(guid):
        return jsonify({"error": "malformed clinic guid"}), 400

    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404
    return jsonify(clinic.to_dict())


@bp.route("/<guid>", methods=["PATCH"])
@require_auth
def update_clinic(guid):
    # #805: `Clinic.guid` is a real UUID column, so a non-UUID value RAISES
    # at the driver and Flask returns 500 — before the 404 below can run. The
    # 404 branch was unreachable for exactly the inputs it was written for.
    #
    # 400 rather than 404 on purpose: they are different answers. 404 says
    # "no such clinic", 400 says "that is not an identifier". A consumer
    # cannot tell a 500 from "the service is down" — which is how #730 became
    # a reported sibling outage — nor a 404 from "my input was rubbish".
    if not is_uuid(guid):
        return jsonify({"error": "malformed clinic guid"}), 400

    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        clinic.name = data["name"]
    if "identifier" in data:
        clinic.identifier = data["identifier"]
    if "is_active" in data:
        clinic.is_active = data["is_active"]

    log_event("clinic_update", resource_guid=clinic.guid)
    db.session.commit()
    return jsonify(clinic.to_dict())


@bp.route("/<guid>/patients", methods=["GET"])
@require_auth
def list_clinic_patients(guid):
    """List active patients assigned to a clinic.

    Returns the same PatientIndex.to_dict() shape as the rest of the
    application API, ordered by (family_name, given_name). The join
    goes through PatientClinicAssignment; duplicates are impossible
    thanks to the (patient_guid, clinic_guid) unique constraint.
    """
    # #805: `Clinic.guid` is a real UUID column, so a non-UUID value RAISES
    # at the driver and Flask returns 500 — before the 404 below can run. The
    # 404 branch was unreachable for exactly the inputs it was written for.
    #
    # 400 rather than 404 on purpose: they are different answers. 404 says
    # "no such clinic", 400 says "that is not an identifier". A consumer
    # cannot tell a 500 from "the service is down" — which is how #730 became
    # a reported sibling outage — nor a 404 from "my input was rubbish".
    if not is_uuid(guid):
        return jsonify({"error": "malformed clinic guid"}), 400

    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    patients = (
        db.session.query(PatientIndex)
        .join(
            PatientClinicAssignment,
            PatientClinicAssignment.patient_guid == PatientIndex.guid,
        )
        .filter(PatientClinicAssignment.clinic_guid == clinic.guid)
        .filter(PatientIndex.is_active.is_(True))
        .order_by(PatientIndex.family_name, PatientIndex.given_name)
        .all()
    )
    return jsonify([p.to_dict() for p in patients])


@bp.route("/<guid>/generate-cohort", methods=["POST"])
@require_auth
def generate_cohort(guid):
    """Generate a synthetic cohort for this clinic, over HTTP (#814).

    The generator previously had two callers — the SU-SSO admin form and a
    Flask CLI command — so a tool outside a browser could not create a cohort.
    sim.pdhc's web Cohort Builder needs to, since "pick a clinic, make 10
    patients aged 40-75, then generate their data" is one operator task and
    splitting it across two UIs is how the batch GUID gets lost.

    This opens no new capability: `POST /api/v1/clinics/<guid>/patients` above
    already lets an API-key holder create patients one at a time, and sim's
    Synthea importer does exactly that in bulk. This is the same power with
    the names, dates and euIPS sections filled in.

    Body (all optional except nothing)::

        {"count": 10, "age_min": 40, "age_max": 75, "skip_clinical": true}

    `age_min`/`age_max` are AGES, not birth years. A bad range is refused with
    400 rather than clamped: a cohort generated for the wrong ages looks
    exactly like one generated for the right ages, so there is no later
    symptom to catch it.

    `skip_clinical` defaults to **true** here, unlike the admin form. A caller
    reaching this endpoint is a generator pipeline, and the usual next step is
    sim.pdhc supplying the observations — two sources of clinical truth for one
    patient is the thing the flag exists to prevent.

    Returns the generator's report, including the **batch_guid**, which is what
    makes the cohort selectable and purgeable as a unit.
    """
    from app.services import mock_generator

    if not is_uuid(guid):
        return jsonify({"error": "malformed clinic guid"}), 400

    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404
    if not clinic.organisation_guid:
        # The same refusal the CLI makes. Patients with no resolvable
        # organisation are invisible to every org-scoped reader, which means
        # the data is collected and then cannot be read by whoever collected
        # it.
        return jsonify({
            "error": f"clinic {clinic.name!r} has no organisation_guid, so "
                     f"its patients could not be org-scoped"}), 409

    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get("count", 10))
    except (TypeError, ValueError):
        return jsonify({"error": "count must be an integer"}), 400
    if count < 1:
        return jsonify({"error": "count must be at least 1"}), 400

    skip_clinical = body.get("skip_clinical")
    skip_clinical = True if skip_clinical is None else bool(skip_clinical)

    try:
        report = mock_generator.generate(
            guid, count=count, skip_clinical=skip_clinical,
            age_min=body.get("age_min"), age_max=body.get("age_max"))
    except mock_generator.AgeRangeError as exc:
        return jsonify({"error": f"age range rejected: {exc}"}), 400

    log_event("patient_cohort_generate", resource_type="Patient",
              detail={"clinic_guid": str(guid),
                      "batch_guid": report.get("batch_guid"),
                      "created": report.get("created"),
                      "age_min": report.get("age_min"),
                      "age_max": report.get("age_max"),
                      "skip_clinical": report.get("skip_clinical")})
    # `log_event` does add + flush and leaves the commit to the caller — all
    # 32 call sites in this service commit after it. Without this the audit
    # row is flushed into a transaction nobody commits and discarded when the
    # request ends, which is exactly how #811's archive landed in production
    # with no audit entry while the test suite stayed green.
    db.session.commit()
    return jsonify(report), 201


@bp.route("/<guid>/patients", methods=["POST"])
@require_auth
def create_clinic_patient(guid):
    """Programmatic create-patient endpoint for cross-service imports.

    Companion to the admin form `create_patient` — same effect
    (PatientIndex + PatientClinicAssignment row), but driven by JSON
    instead of HTML form data. Used by sim.pdhc's Synthea importer
    (Shape C of the synthea hookup proposal): the importer maps each
    Synthea Patient bundle to one POST here, the patient lands in
    ips.pdhc with a clinic assignment, and the next Cohort Builder
    run sees them in the roster.

    Request body — minimal shape::

        {
          "family_name": "Lindberg",
          "given_name":  "Olof",
          "gender":      "male",      # optional
          "birth_date":  "1948-09-18",  # optional, ISO date
          "identifier_system": "...",   # optional
          "identifier_value":  "...",   # optional, system-level identifier
        }

    Alternatively, pass a full FHIR Patient resource under "fhir":

        {"fhir": {"resourceType": "Patient", "name": [...], ...}}

    The endpoint normalises both shapes into a FHIR Patient resource,
    saves it (which `_sync_patient_index` then materialises into the
    PatientIndex row), and INSERTs a PatientClinicAssignment row
    against the URL's clinic guid.

    Returns the created PatientIndex dict + 201.
    """
    # #805: `Clinic.guid` is a real UUID column, so a non-UUID value RAISES
    # at the driver and Flask returns 500 — before the 404 below can run. The
    # 404 branch was unreachable for exactly the inputs it was written for.
    #
    # 400 rather than 404 on purpose: they are different answers. 404 says
    # "no such clinic", 400 says "that is not an identifier". A consumer
    # cannot tell a 500 from "the service is down" — which is how #730 became
    # a reported sibling outage — nor a 404 from "my input was rubbish".
    if not is_uuid(guid):
        return jsonify({"error": "malformed clinic guid"}), 400

    clinic = db.session.query(Clinic).filter_by(guid=guid).first()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    data = request.get_json(silent=True) or {}

    # If a full FHIR Patient was supplied, accept it; otherwise build
    # one from the flat fields.
    if "fhir" in data and isinstance(data["fhir"], dict):
        patient_fhir = dict(data["fhir"])
        if patient_fhir.get("resourceType") != "Patient":
            return jsonify({
                "error": "fhir.resourceType must be 'Patient'",
            }), 400
        # Ensure an id is present — _sync_patient_index keys on it.
        patient_fhir.setdefault("id", str(uuid.uuid4()))
    else:
        family = (data.get("family_name") or "").strip()
        given = (data.get("given_name") or "").strip()
        if not family or not given:
            return jsonify({
                "error": "family_name and given_name are required "
                         "(or supply a complete fhir.Patient body)",
            }), 400
        resource_id = str(uuid.uuid4())
        patient_fhir = {
            "resourceType": "Patient",
            "id": resource_id,
            "name": [{
                "use": "official",
                "family": family,
                "given": [given],
            }],
            "gender": (data.get("gender") or "unknown"),
        }
        if data.get("birth_date"):
            patient_fhir["birthDate"] = data["birth_date"]
        if data.get("identifier_value"):
            # #789: this endpoint DEFAULTS the system to the Swedish
            # personnummer OID, so an unqualified value is implicitly a claim
            # that it is a personnummer. Normalise and validate only on that
            # system — a caller passing its own identifier_system is not
            # asserting anything about Swedish format and must not be judged
            # against it (10 live patients carry US SSNs from the Synthea
            # import, and those are foreign identifiers, not broken ones).
            #
            # Warn rather than reject: this is a live endpoint with external
            # callers, and turning a 201 into a 400 is a breaking change that
            # belongs in its own ticket, not in a format fix.
            id_system = data.get("identifier_system") or pnr.PERSONNUMMER_SYSTEM
            id_value = data["identifier_value"]
            if id_system == pnr.PERSONNUMMER_SYSTEM:
                id_value = pnr.normalise(id_value) or id_value
                problem = pnr.describe_invalid(
                    id_value, birth=data.get("birth_date") or None)
                if problem:
                    current_app.logger.warning(
                        "patient create via clinic %s: questionable "
                        "personnummer (%s)", guid, problem)
            patient_fhir["identifier"] = [{
                "system": id_system,
                "value": id_value,
            }]
        if clinic.organisation_guid:
            patient_fhir["managingOrganization"] = {
                "reference": f"Organization/{clinic.organisation_guid}",
                "display": clinic.name,
            }

    create_resource("Patient", patient_fhir)
    pi = (
        db.session.query(PatientIndex)
        .filter_by(resource_id=patient_fhir["id"])
        .first()
    )
    if pi is None:
        # _sync_patient_index didn't populate PatientIndex — something
        # is wrong with the FHIR body (e.g., no name).
        db.session.rollback()
        return jsonify({
            "error": "PatientIndex was not created from the supplied FHIR; "
                     "the resource probably lacks the required fields (name).",
        }), 400

    db.session.add(PatientClinicAssignment(
        patient_guid=pi.guid,
        clinic_guid=clinic.guid,
    ))
    log_event("clinic_patient_create", resource_guid=pi.guid)
    db.session.commit()
    return jsonify(pi.to_dict()), 201
