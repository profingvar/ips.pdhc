"""Patient-centric query routes.

Today this blueprint only carries the inverse of
`GET /api/v1/clinics/<guid>/patients` — i.e. given a patient, return
the clinics they are assigned to. Future patient-portal routes
(self-block management, self-consent — IPS Renov tickets #199 / #200)
will mount here too.
"""
import uuid

from flask import Blueprint, current_app, jsonify, request

from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import euips_header as euips_hdr
from app.services import euips_sections as euips
from app.services.auth_service import require_auth
from app.services.consent_policy import evaluate_patient
from app.services.ips_generator import (
    _custodian_clinic, custodian_disagreement, generate_ips_bundle,
)

bp = Blueprint("patient_api", __name__, url_prefix="/api/v1/patients")


def _is_uuid(value) -> bool:
    """True when `value` parses as a UUID.

    Hoisted out of `analysis_filter` by #791, which needed it too. It was
    defined inside that function when #730 added it; a second copy in the new
    route would be two definitions of one rule, and the shape that cost #784
    and #786 a day each.
    """
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


@bp.route("/<guid>/clinics", methods=["GET"])
@require_auth
def list_patient_clinics(guid):
    """List active clinics a patient is assigned to.

    Used by request.pdhc (and other downstream services) to enforce
    patient-org need-to-know at write-side endpoints — see PDL
    Ch 4 §§ 1-2 and ticket #225.

    Returns the Clinic.to_dict() shape, ordered by name. Empty list
    when the patient exists but has no assignments. 404 when the
    patient does not exist.
    """
    patient = db.session.query(PatientIndex).filter_by(guid=guid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    clinics = (
        db.session.query(Clinic)
        .join(
            PatientClinicAssignment,
            PatientClinicAssignment.clinic_guid == Clinic.guid,
        )
        .filter(PatientClinicAssignment.patient_guid == patient.guid)
        .filter(Clinic.is_active.is_(True))
        .order_by(Clinic.name)
        .all()
    )
    return jsonify([c.to_dict() for c in clinics])


@bp.route("/analysis-filter", methods=["POST"])
@require_auth
def analysis_filter():
    """Apply the canonical analysis consent policy (#422) to a set of patients.

    ips owns the D1 consent flags, so it owns the enforcement: analysis
    services (analyse.pdhc, rosetta, cdr2-6) POST the candidate patient guids +
    their read context here and receive back only the patients they may read,
    plus the reason each excluded patient was dropped.

    Body:
        {
          "patient_guids": ["...", ...],
          "purpose": "research" | "statistics" | "quality_registry" | ...,
          "research_project_guids": ["...", ...]   # reader's affiliation projects
        }

    Returns:
        {
          "purpose": "...",
          "allowed": ["...guids..."],
          "excluded": [{"patient_guid": "...", "reason": "ehds_opt_out" | ...}]
        }
    """
    data = request.get_json(silent=True) or {}
    guids = data.get("patient_guids") or []
    purpose = (data.get("purpose") or "").strip()
    reader_projects = data.get("research_project_guids") or []

    if not purpose:
        return jsonify({"error": "purpose is required"}), 400
    if not isinstance(guids, list):
        return jsonify({"error": "patient_guids must be a list"}), 400

    # `PatientIndex.guid` is a UUID column, so a guid that is not a well-formed
    # UUID made the IN clause raise at the driver — "badly formed hexadecimal
    # UUID string" — and this endpoint answered **500**.
    #
    # That is the worst available answer for a consent gate. A caller sees an
    # exception, not a verdict, and a 500 is indistinguishable from ips being
    # down: cdr's `_analysis_filter` turns it into `IpsUnreachable` and
    # fail-closes the whole read, reporting a sibling outage. One malformed
    # guid anywhere in a cohort therefore denied the entire cohort and blamed
    # the wrong service. Found by cdr's sibling smoke 2026-10-07, whose probe
    # guid is deliberately not a UUID.
    #
    # Malformed guids are now treated as UNKNOWN rather than fatal: they get
    # empty flags, so they fail closed for that patient alone, and they are
    # named in `excluded` with their own reason so the caller can see that it
    # sent something unusable instead of inferring an outage. Per-patient
    # fail-closed beats per-request, and neither should be a 500.
    queryable = [g for g in guids if _is_uuid(g)]
    malformed = {str(g) for g in guids if not _is_uuid(g)}
    if malformed:
        current_app.logger.warning(
            "analysis-filter: %d of %d patient_guids are not well-formed "
            "UUIDs; treating as unknown and excluding them: %s",
            len(malformed), len(guids), sorted(malformed)[:5])

    # Load flags for the patients we know about; unknown guids get empty flags
    # (opt-outs default False; research consent empty -> excluded from research).
    rows = (
        db.session.query(PatientIndex)
        .filter(PatientIndex.guid.in_(queryable))
        .all()
    ) if queryable else []
    flags_by_guid = {
        str(p.guid): {
            "ehds_opt_out": p.ehds_opt_out,
            "quality_registry_opt_out": p.quality_registry_opt_out,
            "consented_research_projects": p.consented_research_projects or [],
        }
        for p in rows
    }

    allowed = []
    excluded = []
    for g in guids:
        if str(g) in malformed:
            # Never allowed, and named rather than silently dropped — a guid
            # that vanished from both lists would look like a shorter cohort.
            excluded.append({"patient_guid": g, "reason": "malformed_guid"})
            continue
        ok, reason = evaluate_patient(
            flags_by_guid.get(str(g), {}), purpose, reader_projects)
        if ok:
            allowed.append(g)
        else:
            excluded.append({"patient_guid": g, "reason": reason})

    return jsonify({
        "purpose": purpose,
        "allowed": allowed,
        "excluded": excluded,
    })


@bp.route("/<guid>/euips-sections", methods=["GET"])
@require_auth
def euips_section_status(guid):
    """euIPS section coverage for one patient — #791. Read-only, COMPUTED.

    Deliberately not backed by a table. A stored copy of a derivable fact is
    the shape that produced #779 (two identifier spaces compared as if one) and
    #771 (two GUIDs for one object), so the status is derived from the
    patient's `fhir_resources` on every call.

    Each section is PRESENT, EXPLICITLY_ABSENT or MISSING. That distinction is
    the point: the euIPS guideline requires a required section to state "no
    known allergies" rather than be empty, and before this "no row" could not
    be told apart from "the clinician recorded nothing to report". Measured
    2026-10-07, 110 of 150 patients had no rows in any section.

    `conformant` reports only that every REQUIRED section is PRESENT or
    EXPLICITLY_ABSENT. It is not a conformance claim: the source document
    states the EHDS technical specifications were not confirmed adopted, and
    the section codes in the catalogue are not yet verified against the
    published IG (`codes_verified` below says so in the response rather than
    leaving the caller to assume).
    """
    if not _is_uuid(guid):
        return jsonify({"error": "malformed patient guid"}), 400

    patient = db.session.query(PatientIndex).filter_by(guid=guid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    rows = (db.session.query(FhirResource)
            .filter(FhirResource.patient_guid == patient.guid)
            .all())
    status = euips.status_for_resources(rows)

    sections = []
    for s in euips.SECTIONS:
        sections.append({
            "key": s.key,
            "title": s.title,
            "obligation": s.obligation,
            "status": status[s.key],
            "resource_types": list(s.resource_types),
        })

    missing_required = [k for k in euips.REQUIRED_KEYS
                        if status[k] == euips.MISSING]

    return jsonify({
        "patient_guid": str(patient.guid),
        "generation_batch_guid": (str(patient.generation_batch_guid)
                                  if patient.generation_batch_guid else None),
        "sections": sections,
        "summary": {
            lvl: {
                st: sum(1 for s in euips.SECTIONS
                        if s.obligation == lvl and status[s.key] == st)
                for st in (euips.PRESENT, euips.EXPLICITLY_ABSENT,
                           euips.MISSING)
            }
            for lvl in euips.OBLIGATION_ORDER
        },
        "required_sections_missing": missing_required,
        "conformant": euips.is_conformant(status),
        # Stated in the response, not buried in a docstring: a caller must not
        # read `conformant` as an EU conformance claim.
        "codes_verified": euips.CODES_VERIFIED,
        "disclaimer": (
            "Checks the obligation levels described in "
            "docs/EU_Patient_Summary_ICD11.docx. NOT a claim of EU/EHDS "
            "conformance: the implementing acts were not confirmed adopted as "
            "of October 2026, and the section codes are not yet verified "
            "against the published IPS implementation guide."
        ),
    })


@bp.route("/<guid>/euips-header", methods=["GET"])
@require_auth
def euips_header_status(guid):
    """euIPS document-header coverage for one patient — #792. COMPUTED.

    The companion to `/euips-sections`. The sections are the summary's content;
    the header is what makes it a document — who the patient is, who may be
    contacted, who pays, who authored and attests to it, who keeps it, in what
    language and country.

    Derived on every call for the same reason the section status is: a stored
    copy of a derivable fact is the shape that produced #779 (two identifier
    spaces compared as one) and #771 (two GUIDs for one object).

    `legal_guardian` reports `not_applicable` for an adult rather than
    `missing`. That distinction is the point of #792's data-quality note: an
    adult without a guardian is correct, and scoring it as a gap would push
    the generator toward manufacturing one.

    THE CUSTODIAN IS DERIVED FROM THE CLINIC ASSIGNMENT, never from the
    Patient's `managingOrganization`. `custodian_mismatch` is non-null when
    those two disagree — the #768 shape, where three organisation identifiers
    on one datapoint failed to collapse. The assignment wins and the
    disagreement is reported rather than silently resolved.
    """
    if not _is_uuid(guid):
        return jsonify({"error": "malformed patient guid"}), 400

    patient = db.session.query(PatientIndex).filter_by(guid=guid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    rows = (db.session.query(FhirResource)
            .filter(FhirResource.patient_guid == patient.guid)
            .filter(FhirResource.status == "active")
            .all())
    patient_json = next(
        (r.resource_json for r in rows if r.resource_type == "Patient"), None)
    if patient_json is None:
        # The index row exists but the Patient resource does not — report it
        # rather than 500ing, which is what #730 taught about a gate that
        # answers with an exception instead of a verdict.
        return jsonify({"error": "patient index row has no active Patient "
                                 "resource"}), 409

    related = [r.resource_json for r in rows
               if r.resource_type == "RelatedPerson"]
    coverage = [r.resource_json for r in rows if r.resource_type == "Coverage"]

    # Build the real document so the header reported is the header shipped,
    # not a second opinion about it. Asking the generator is what keeps this
    # endpoint from drifting away from the bundle.
    bundle = generate_ips_bundle(patient)
    composition = next(
        (e["resource"] for e in bundle.get("entry", ())
         if e.get("resource", {}).get("resourceType") == "Composition"), None)

    status = euips_hdr.header_status(
        patient_json=patient_json, related=related, coverage=coverage,
        composition=composition)

    clinic = _custodian_clinic(patient)
    status.update({
        "patient_guid": str(patient.guid),
        "custodian": {
            "organisation_guid": (str(clinic.organisation_guid)
                                  if clinic else None),
            "name": clinic.name if clinic else None,
            "source": "PatientClinicAssignment (authoritative)",
        },
        "custodian_mismatch": custodian_disagreement(patient_json, clinic),
        "language": composition.get("language") if composition else None,
        "country_of_origin": euips_hdr.COUNTRY_OF_ORIGIN,
        "disclaimer": (
            "Reports the document-header elements described in "
            "docs/EU_Patient_Summary_ICD11.docx. NOT a claim of EU/EHDS "
            "conformance: the implementing acts were not confirmed adopted as "
            "of October 2026, and neither the codes nor the R5 element shapes "
            "here are verified against the published IPS implementation guide."
        ),
    })
    return jsonify(status)
