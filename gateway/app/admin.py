"""Admin UI blueprint — lightweight operator dashboard."""

import json
import uuid
import logging
from datetime import datetime, timezone, date

import httpx
from flask import (
    Blueprint, render_template, request, abort, make_response,
    session, redirect, url_for, current_app, flash,
)
from sqlalchemy import text, func, or_
from werkzeug.security import generate_password_hash

from app.models.base import db
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import personnummer as pnr
from app.services import euips_recommended, euips_required, euips_sections
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.services.ips_generator import generate_ips_bundle
from app.services.fhir_service import create_resource

logger = logging.getLogger(__name__)

bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
)


@bp.before_request
def _require_session():
    """Redirect to SSO login if no active session (skipped when AUTH_DISABLED)."""
    if current_app.config.get("AUTH_DISABLED"):
        return None
    # Allow docs downloads without login
    if request.endpoint and "download" in request.endpoint:
        return None
    if not session.get("sso_user"):
        session["sso_next"] = request.url
        return redirect(url_for("sso.login"))
    return None


# ── Dashboard ────────────────────────────────────────────────

@bp.route("/")
def dashboard():
    """Admin dashboard — service status and resource counts."""
    try:
        db.session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    counts = {}
    try:
        counts = {
            "patients": db.session.query(PatientIndex).count(),
            "resources": db.session.query(FhirResource).filter_by(status="active").count(),
            "cards": db.session.query(IpsCard).filter_by(status="active").count(),
            "snapshots": db.session.query(IpsSnapshot).count(),
            "push_jobs": db.session.query(PushJob).count(),
            "audit_events": db.session.query(AuditLog).count(),
        }
    except Exception:
        pass

    recent_audit = []
    try:
        recent_audit = db.session.query(AuditLog).order_by(
            AuditLog.created_at.desc()
        ).limit(20).all()
    except Exception:
        pass

    # Sync organisations from SSO into local Clinic table
    orgs = _sync_sso_organisations()

    return render_template(
        "dashboard.html",
        db_status=db_status,
        counts=counts,
        recent_audit=recent_audit,
        orgs=orgs,
    )


# ── Patient Browser ──────────────────────────────────────────

@bp.route("/patients")
def patients():
    """Patient browser — search and list patients."""
    q = request.args.get("q", "").strip()

    query = db.session.query(PatientIndex).order_by(PatientIndex.family_name)

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                PatientIndex.family_name.ilike(like_q),
                PatientIndex.given_name.ilike(like_q),
                PatientIndex.identifier_value.ilike(like_q),
            )
        )

    patients_list = query.limit(100).all()

    for p in patients_list:
        p.card_count = db.session.query(IpsCard).filter_by(patient_guid=p.guid).count()
        p.resource_count = db.session.query(FhirResource).filter_by(
            patient_guid=p.guid, status="active"
        ).count()
        # Extract organisation from FHIR Patient resource
        pat_res = db.session.query(FhirResource).filter_by(
            resource_id=p.resource_id, resource_type="Patient", status="active"
        ).first()
        org = (pat_res.resource_json or {}).get("managingOrganization", {}) if pat_res else {}
        p.organisation = org.get("display", "—")

    # #790: the mock-patient generator moved here from the dashboard, and its
    # organisation select is labelled "synced from SSO". That sync ran in the
    # dashboard view, so simply moving the markup would have quietly dropped it
    # and a newly created SSO organisation would not appear until somebody
    # visited the dashboard.
    #
    # `_sync_sso_organisations()` ends with exactly the query this line used to
    # run — active clinics by name — so `orgs` and `clinics` are the same list;
    # the sync only refreshes it first, and it degrades gracefully (logs a
    # warning, returns the local rows) when SSO is unreachable. Both names are
    # passed because the Create form and the generator each use their own.
    orgs = _sync_sso_organisations()
    clinics = orgs
    return render_template("patients.html", patients=patients_list, q=q,
                           clinics=clinics, orgs=orgs)


@bp.route("/patients/create", methods=["POST"])
def create_patient():
    """Create a patient from the admin UI."""
    family = request.form.get("family_name", "").strip()
    given = request.form.get("given_name", "").strip()
    birth = request.form.get("birth_date", "").strip()
    gender = request.form.get("gender", "").strip()
    identifier = request.form.get("identifier", "").strip()

    if not family or not given:
        flash("Family name and given name are required.", "error")
        return redirect(url_for("admin.patients"))

    clinic_guid = request.form.get("clinic_guid", "").strip()
    clinic = db.session.query(Clinic).filter_by(guid=clinic_guid).first() if clinic_guid else None

    resource_id = str(uuid.uuid4())
    patient_fhir = {
        "resourceType": "Patient",
        "id": resource_id,
        "name": [{"family": family, "given": [given], "use": "official"}],
        "gender": gender or "unknown",
    }
    if birth:
        patient_fhir["birthDate"] = birth
    if identifier:
        # #789: this form stores whatever is typed under the Swedish
        # personnummer OID, so a malformed value becomes a false claim about
        # the identifier's system. Normalise the short form an operator
        # naturally types (YYMMDD-NNNN) and WARN rather than reject: an
        # operator may be recording a real patient whose details are
        # imperfect, and refusing the save would lose the rest of the record.
        normalised = pnr.normalise(identifier) or identifier
        problem = pnr.describe_invalid(normalised, birth=birth or None)
        if problem:
            flash(f"Patient saved, but the personnummer looks wrong: {problem}",
                  "warning")
            current_app.logger.warning(
                "patient create: questionable personnummer (%s)", problem)
        patient_fhir["identifier"] = [{
            "system": pnr.PERSONNUMMER_SYSTEM,
            "value": normalised,
        }]
    if clinic:
        patient_fhir["managingOrganization"] = {
            "reference": f"Organization/{clinic.organisation_guid}" if clinic.organisation_guid else None,
            "display": clinic.name,
        }

    create_resource("Patient", patient_fhir)

    # Link to clinic via PatientClinicAssignment so the patient shows
    # up in GET /api/v1/clinics/<guid>/patients (cross-service consumers
    # like sim.pdhc Cohort Builder query through that endpoint).
    # `managingOrganization` on the FHIR resource alone is not enough.
    if clinic:
        pi = db.session.query(PatientIndex).filter_by(resource_id=resource_id).first()
        if pi:
            db.session.add(PatientClinicAssignment(
                patient_guid=pi.guid,
                clinic_guid=clinic.guid,
            ))

    db.session.commit()
    flash(f"Patient {family}, {given} created.", "success")
    return redirect(url_for("admin.patients"))


# ── Patient Detail ───────────────────────────────────────────

@bp.route("/patients/<uuid:guid>")
def patient_detail(guid):
    """Patient detail — resources, cards, and snapshots."""
    patient = db.session.get(PatientIndex, guid)
    if not patient:
        abort(404)

    resources = db.session.query(FhirResource).filter_by(
        patient_guid=guid, status="active"
    ).order_by(FhirResource.resource_type, FhirResource.last_updated.desc()).all()

    cards = db.session.query(IpsCard).filter_by(
        patient_guid=guid
    ).order_by(IpsCard.created_at.desc()).all()

    snapshots = db.session.query(IpsSnapshot).join(IpsCard).filter(
        IpsCard.patient_guid == guid
    ).order_by(IpsSnapshot.created_at.desc()).all()

    # Active destinations for push form
    destinations = db.session.query(PushDestination).filter_by(
        is_active=True
    ).order_by(PushDestination.name).all()

    return render_template(
        "patient_detail.html",
        patient=patient,
        resources=resources,
        cards=cards,
        snapshots=snapshots,
        snapshot_count=len(snapshots),
        destinations=destinations,
    )


@bp.route("/patients/<uuid:guid>/add-resource", methods=["POST"])
def add_resource(guid):
    """Add a clinical resource to a patient from admin UI."""
    patient = db.session.get(PatientIndex, guid)
    if not patient:
        abort(404)

    res_type = request.form.get("resource_type", "").strip()
    if res_type not in (
        "Condition", "Observation", "MedicationStatement",
        "AllergyIntolerance", "Immunization", "Procedure",
    ):
        flash("Invalid resource type.", "error")
        return redirect(url_for("admin.patient_detail", guid=guid))

    resource_id = str(uuid.uuid4())
    code_text = request.form.get("code_text", "").strip() or f"Sample {res_type}"
    code_system = request.form.get("code_system", "").strip() or "http://snomed.info/sct"
    code_value = request.form.get("code_value", "").strip() or "unknown"

    resource_json = {
        "resourceType": res_type,
        "id": resource_id,
        "subject": {"reference": f"Patient/{patient.resource_id}"},
        "code": {
            "coding": [{"system": code_system, "code": code_value, "display": code_text}],
            "text": code_text,
        },
    }

    # Type-specific fields
    if res_type == "Condition":
        resource_json["clinicalStatus"] = {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active"}]
        }
    elif res_type == "MedicationStatement":
        resource_json["status"] = "active"
        resource_json["medication"] = resource_json.pop("code")
        resource_json["subject"] = resource_json.get("subject")
    elif res_type == "AllergyIntolerance":
        resource_json["clinicalStatus"] = {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                        "code": "active"}]
        }
        del resource_json["code"]
        resource_json["reaction"] = [{"substance": {
            "coding": [{"system": code_system, "code": code_value, "display": code_text}],
            "text": code_text,
        }}]
    elif res_type == "Observation":
        resource_json["status"] = "final"
    elif res_type == "Immunization":
        resource_json["status"] = "completed"
        resource_json["vaccineCode"] = resource_json.pop("code")
        resource_json["patient"] = resource_json.pop("subject")
        resource_json["occurrenceDateTime"] = datetime.now(timezone.utc).isoformat()
    elif res_type == "Procedure":
        resource_json["status"] = "completed"

    create_resource(res_type, resource_json, patient_guid=patient.guid)
    db.session.commit()
    flash(f"{res_type} added: {code_text}", "success")
    return redirect(url_for("admin.patient_detail", guid=guid))


@bp.route("/patients/<uuid:guid>/create-card", methods=["POST"])
def create_card(guid):
    """Create an IPS card for a patient."""
    patient = db.session.get(PatientIndex, guid)
    if not patient:
        abort(404)

    title = request.form.get("title", "").strip() or "International Patient Summary"
    mode = request.form.get("mode", "full")

    card = IpsCard(
        patient_guid=patient.guid,
        title=title,
        mode=mode,
    )
    db.session.add(card)
    db.session.commit()
    flash(f"IPS Card created: {title} ({mode})", "success")
    return redirect(url_for("admin.patient_detail", guid=guid))


@bp.route("/patients/<uuid:guid>/create-snapshot/<uuid:card_guid>", methods=["POST"])
def create_snapshot(guid, card_guid):
    """Generate a snapshot for an IPS card."""
    patient = db.session.get(PatientIndex, guid)
    card = db.session.query(IpsCard).filter_by(guid=card_guid).first()
    if not patient or not card:
        abort(404)

    now = datetime.now(timezone.utc)
    bundle = generate_ips_bundle(patient, mode=card.mode, composition_date=now)

    snapshot = IpsSnapshot(
        card_guid=card.guid,
        bundle_json=bundle,
        composition_date=now,
        mode=card.mode,
        resource_count=len(bundle.get("entry", [])),
    )
    db.session.add(snapshot)
    db.session.commit()
    flash(f"Snapshot generated with {snapshot.resource_count} entries.", "success")
    return redirect(url_for("admin.patient_detail", guid=guid))


@bp.route("/patients/<uuid:guid>/push-snapshot", methods=["POST"])
def push_snapshot(guid):
    """Create a push job for a snapshot."""
    snapshot_guid = request.form.get("snapshot_guid", "")
    destination_guid = request.form.get("destination_guid", "")

    snapshot = db.session.query(IpsSnapshot).filter_by(guid=snapshot_guid).first()
    dest = db.session.query(PushDestination).filter_by(guid=destination_guid, is_active=True).first()

    if not snapshot or not dest:
        flash("Snapshot or destination not found.", "error")
        return redirect(url_for("admin.patient_detail", guid=guid))

    job = PushJob(
        snapshot_guid=snapshot.guid,
        destination_guid=dest.guid,
    )
    db.session.add(job)
    db.session.commit()
    flash(f"Push job queued to {dest.name}.", "success")
    return redirect(url_for("admin.patient_detail", guid=guid))


# ── Push Monitor ─────────────────────────────────────────────

@bp.route("/push")
def push_monitor():
    """Push monitor — destinations, jobs, statuses."""
    status_filter = request.args.get("status", "").strip()

    destinations = db.session.query(PushDestination).order_by(
        PushDestination.name
    ).all()
    for d in destinations:
        d.job_count = db.session.query(PushJob).filter_by(
            destination_guid=d.guid
        ).count()

    job_query = db.session.query(PushJob).order_by(PushJob.created_at.desc())
    if status_filter:
        job_query = job_query.filter_by(status=status_filter)
    jobs = job_query.limit(100).all()

    stats = {
        "queued": db.session.query(PushJob).filter_by(status="queued").count(),
        "in_progress": db.session.query(PushJob).filter_by(status="in_progress").count(),
        "completed": db.session.query(PushJob).filter_by(status="completed").count(),
        "failed": db.session.query(PushJob).filter_by(status="failed").count(),
    }

    return render_template(
        "push_monitor.html",
        destinations=destinations,
        jobs=jobs,
        stats=stats,
        status_filter=status_filter,
    )


@bp.route("/push/create-destination", methods=["POST"])
def create_destination():
    """Create a push destination from admin UI."""
    name = request.form.get("name", "").strip()
    dest_type = request.form.get("destination_type", "fhir").strip()
    endpoint = request.form.get("endpoint_url", "").strip()

    if not name or not endpoint:
        flash("Name and endpoint URL are required.", "error")
        return redirect(url_for("admin.push_monitor"))

    dest = PushDestination(
        name=name,
        destination_type=dest_type,
        endpoint_url=endpoint,
        auth_method=request.form.get("auth_method", "").strip() or None,
    )
    db.session.add(dest)
    db.session.commit()
    flash(f"Destination created: {name}", "success")
    return redirect(url_for("admin.push_monitor"))


# ── SSO Organisation Sync ─────────────────────────────────────

def _sync_sso_organisations():
    """Fetch organisations from SSO and upsert into local Clinic table.
    Returns list of local Clinic objects."""
    sso_orgs = []
    try:
        base_url = current_app.config.get("OAUTH_BASE_URL", "https://sso.pdhc.se")
        resp = httpx.get(f"{base_url}/api/public/organisations", timeout=10.0)
        if resp.status_code == 200:
            sso_orgs = resp.json()
    except httpx.RequestError:
        logger.warning("Could not reach SSO for organisations")

    # Upsert into local Clinic table
    for org in sso_orgs:
        org_guid = org.get("organisation_guid") or org.get("guid", "")
        name = org.get("name", "Unknown")
        if not org_guid:
            continue

        clinic = db.session.query(Clinic).filter_by(organisation_guid=org_guid).first()
        if clinic:
            if clinic.name != name:
                clinic.name = name
        else:
            clinic = Clinic(
                organisation_guid=org_guid,
                name=name,
                identifier=org_guid,
                is_active=True,
            )
            db.session.add(clinic)

    if sso_orgs:
        db.session.commit()

    # Return all active clinics (includes any that were added manually)
    return db.session.query(Clinic).filter_by(is_active=True).order_by(Clinic.name).all()


# ── Mock Data Generator ──────────────────────────────────────

# Combinatorial Swedish name pool — 40 family × (30 male + 30 female)
# = 2400 unique (family, given) combinations. The mock-data endpoint
# samples without replacement up to its cap (150) so every generated
# patient has a unique name within a single batch.
_SWEDISH_FAMILY = [
    "Andersson", "Johansson", "Karlsson", "Nilsson", "Eriksson",
    "Larsson", "Olsson", "Persson", "Svensson", "Gustafsson",
    "Pettersson", "Jonsson", "Jansson", "Hansson", "Bengtsson",
    "Jönsson", "Lindberg", "Jakobsson", "Magnusson", "Olofsson",
    "Lindström", "Lindqvist", "Lindgren", "Berg", "Axelsson",
    "Berglund", "Bergström", "Lundberg", "Lundgren", "Lundqvist",
    "Mattsson", "Berggren", "Sandberg", "Henriksson", "Forsberg",
    "Sjöberg", "Wallin", "Engström", "Eklund", "Holmgren",
]

_SWEDISH_GIVEN_M = [
    "Erik", "Lars", "Karl", "Anders", "Per", "Mikael", "Johan",
    "Olof", "Nils", "Sven", "Jan", "Hans", "Gunnar", "Bo", "Bengt",
    "Magnus", "Stefan", "Daniel", "Tomas", "Mats", "Niklas", "Fredrik",
    "Henrik", "Andreas", "David", "Martin", "Oscar", "Jonas",
    "Alexander", "Filip",
]

_SWEDISH_GIVEN_F = [
    "Anna", "Eva", "Maria", "Karin", "Sara", "Lena", "Birgitta",
    "Christina", "Ingrid", "Margareta", "Elisabeth", "Marianne",
    "Kerstin", "Astrid", "Linda", "Susanne", "Ulla", "Inger",
    "Helena", "Monica", "Cecilia", "Hanna", "Lisa", "Emma",
    "Sofia", "Julia", "Lina", "Klara", "Elin", "Alva",
]


def _build_unique_patient_pool(count: int) -> list[dict]:
    """Sample up to ``count`` unique (family, given, gender, birth)
    dicts from the combinatorial Swedish-name pool.

    The shape mirrors the original `_SWEDISH_NAMES` entries so the
    callsite stays unchanged.
    """
    import random
    male_pool = [(f, g, "male") for f in _SWEDISH_FAMILY for g in _SWEDISH_GIVEN_M]
    female_pool = [(f, g, "female") for f in _SWEDISH_FAMILY for g in _SWEDISH_GIVEN_F]
    pool = male_pool + female_pool
    random.shuffle(pool)
    n = min(count, len(pool))
    out: list[dict] = []
    for family, given, gender in pool[:n]:
        # Birth years 1940–2010, random month/day. We don't try to be
        # epidemiologically realistic — sim.pdhc owns the data semantics
        # and just needs a valid birthDate to attach observations to.
        year = random.randint(1940, 2010)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        out.append({
            "family": family,
            "given": given,
            "gender": gender,
            "birth": f"{year:04d}-{month:02d}-{day:02d}",
        })
    return out

# #793: _CONDITIONS, _MEDICATIONS and _ALLERGIES were removed from here. The
# three euIPS REQUIRED sections are generated by
# app/services/euips_required.py, which owns those vocabularies now — the
# lists here had no remaining reader.
#
# Keeping two copies was not harmless. They DISAGREED: this file labelled
# SNOMED 91936005 as "Peanuts", while the surviving list labels it "Allergy to
# penicillin". One of those is wrong, and nothing would have caught it. The
# codes across this reform are flagged CODES_VERIFIED = False in
# euips_sections.py for exactly this reason, and this discrepancy is recorded
# as a specific item to settle when the terminology is verified against the
# IPS implementation guide — the codes belong to plan.pdhc and termbank.pdhc,
# not here.

# #794: _IMMUNIZATIONS, _PROCEDURES and _DIAGNOSTIC_REPORTS were removed from
# here. Those three recommended sections are generated by
# app/services/euips_recommended.py now, which owns the vocabularies, and the
# lists here had no remaining reader.
#
# Unlike the #793 removal, these did NOT contradict the surviving lists --
# every shared code carried a compatible display. One redundancy was dropped:
# this file listed BOTH LOINC 58410-2 "Complete blood count" and 11502-2 "Full
# blood count", two codes for the same concept, which would have made a cohort
# look as though it contained two different tests.
#
# _OBSERVATIONS stays: vital signs are an OPTIONAL section and #795 owns them.

_OBSERVATIONS = [
    ("8480-6", "Systolic blood pressure", "mmHg", 110, 180),
    ("8462-4", "Diastolic blood pressure", "mmHg", 60, 100),
    ("29463-7", "Body weight", "kg", 55, 110),
    ("8302-2", "Body height", "cm", 155, 195),
    ("4548-4", "HbA1c", "%", 4.5, 10.0),
    ("2093-3", "Total cholesterol", "mmol/L", 3.5, 8.0),
    ("33914-3", "eGFR", "mL/min/1.73m2", 30, 120),
    ("2160-0", "Creatinine", "umol/L", 50, 200),
]

def _mock_patient_resources(resource_id, patient_guid, org_name, mp):
    """Generate the NON-REQUIRED euIPS sections for one mock patient.

    #793 moved allergies, problems and medications OUT of here into
    `euips_required.required_sections_for`, which the caller now runs for every
    patient in both modes. They are the three euIPS REQUIRED sections and may
    never be empty, so they cannot live behind the `skip_clinical` branch that
    guards this function.

    What remains here is recommended and optional content, where plain absence
    is permitted: immunisations, vital-sign observations, procedures and
    diagnostic reports. #794 and #795 extend it.
    """
    import random
    now_iso = datetime.now(timezone.utc).isoformat()

    # #794: immunisations, procedures and diagnostic results moved OUT of
    # here into app/services/euips_recommended.py, which the caller runs for
    # every patient. Three reasons they could not stay:
    #
    #   * medical devices -- one of the four recommended sections -- were never
    #     generated at all, so the section had to be built somewhere anyway;
    #   * immunisation dates were all generation time (97 live rows across 40
    #     distinct dates, every one the moment its batch ran), so an
    #     80-year-old's childhood vaccine was dated today. Dates now derive
    #     from the patient's birth date, which needs the birth date passed in;
    #   * all 61 live DiagnosticReport rows carried NO `result`. A lab section
    #     whose reports reference no observations is a header with a sentence.
    #
    # What remains here is vital-sign Observations, an OPTIONAL section that
    # #795 will take over.

    # Observations (3-5)
    for code, display, unit, lo, hi in random.sample(_OBSERVATIONS, random.randint(3, 5)):
        val = round(random.uniform(lo, hi), 1)
        create_resource("Observation", {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{resource_id}"},
            "status": "final",
            "code": {
                "coding": [{"system": "http://loinc.org", "code": code, "display": display}],
                "text": display,
            },
            "valueQuantity": {"value": val, "unit": unit, "system": "http://unitsofmeasure.org"},
            "effectiveDateTime": now_iso,
        }, patient_guid=patient_guid)



@bp.route("/mock-data", methods=["POST"])
def generate_mock_data():
    """Generate mock patients for a chosen organisation.

    Two modes:
    - Default: full IPS — Patient + clinical resources + IPS card + snapshot.
    - `skip_clinical=on`: just Patient + PatientClinicAssignment. Used
      when sim.pdhc (or another generator) will provide the clinical
      data downstream — avoids polluting cdr_6 with two sources of
      truth for the same patient's observations.

    Cap is 150 to match sim.pdhc's typical cohort smoke runs.
    """
    import random

    clinic_guid = request.form.get("clinic_guid", "")
    count = min(int(request.form.get("count", "4")), 150)
    skip_clinical = request.form.get("skip_clinical", "").lower() in {"on", "1", "true"}

    # Resolve clinic — carries both org_guid and name
    clinic = db.session.query(Clinic).filter_by(guid=clinic_guid).first() if clinic_guid else None
    org_guid = clinic.organisation_guid if clinic else ""
    org_name = clinic.name if clinic else "Demo Clinic"

    patients_pool = _build_unique_patient_pool(count)
    created_count = 0
    created_guids: list = []        # #793: for the conformance count below

    for mp in patients_pool:
        resource_id = str(uuid.uuid4())
        # #789: was `f"19{mp['birth'].replace('-','')}-{randint(1000,9999)}"`.
        # mp['birth'] is already YYYY-MM-DD, so the "19" doubled the century
        # (1919611015-9638, 15 chars instead of 13), and the last digit is a
        # Luhn checksum rather than a free number — valid in 6 of 60 sampled
        # live rows, exactly chance. Worst case was a 2000s birth becoming
        # "19"+"20xx", an identifier contradicting its own birth_date.
        personnummer = pnr.build(mp["birth"])

        patient_fhir = {
            "resourceType": "Patient",
            "id": resource_id,
            "name": [{"family": mp["family"], "given": [mp["given"]], "use": "official"}],
            "gender": mp["gender"],
            "birthDate": mp["birth"],
            "identifier": [{
                "system": "urn:oid:1.2.752.129.2.1.3.1",
                "value": personnummer,
            }],
            "managingOrganization": {
                "reference": f"Organization/{org_guid}" if org_guid else None,
                "display": org_name,
            },
            "address": [{
                "use": "home",
                "city": random.choice(["Stockholm", "Göteborg", "Malmö", "Uppsala", "Lund"]),
                "country": "SE",
            }],
            "telecom": [{
                "system": "phone",
                "value": f"+4670{random.randint(1000000, 9999999)}",
                "use": "mobile",
            }],
        }
        create_resource("Patient", patient_fhir)
        patient = db.session.query(PatientIndex).filter_by(resource_id=resource_id).first()
        if not patient:
            continue

        # Link to clinic via PatientClinicAssignment (same reason as the
        # admin create_patient path: cross-service consumers query the
        # /api/v1/clinics/<guid>/patients endpoint which joins on this
        # table, not on FHIR managingOrganization).
        if clinic:
            db.session.add(PatientClinicAssignment(
                patient_guid=patient.guid,
                clinic_guid=clinic.guid,
            ))

        # #793: the three euIPS REQUIRED sections, ALWAYS, in BOTH modes.
        # The guideline forbids an empty required section -- "you must state
        # 'no known allergies' rather than leave the section empty" -- and
        # measured 2026-10-07 this generator had left 110 of 150 patients with
        # no statement at all in any section.
        #
        # In skip_clinical mode they are emitted as explicit absent
        # assertions, not skipped. skip_clinical exists so sim.pdhc can own the
        # clinical data without two sources of truth, which is a good reason;
        # it is not a reason to create a non-conformant patient in the
        # meantime. sim's real content supersedes them later, because
        # status_for_resources prefers real content over a stale absent
        # assertion.
        for body in euips_required.required_sections_for(
                f"Patient/{resource_id}", absent_only=skip_clinical):
            create_resource(body["resourceType"], body,
                            patient_guid=patient.guid)

        if not skip_clinical:
            # #794: the four RECOMMENDED sections — immunisations, procedures,
            # medical devices (which never existed before) and diagnostic
            # results with their actual Observations. Emitted in dependency
            # order, so an Observation is written before the DiagnosticReport
            # that references it and no dangling reference is ever created.
            #
            # Unlike the required three these may legitimately be absent, so a
            # section can come back as content, as an explicit "none known", or
            # as nothing at all. All three are valid here.
            for body in euips_recommended.recommended_sections_for(
                    f"Patient/{resource_id}", mp["birth"]):
                create_resource(body["resourceType"], body,
                                patient_guid=patient.guid)

            # Vital-sign Observations only — the OPTIONAL section #795 owns.
            _mock_patient_resources(resource_id, patient.guid, org_name, mp)

            # Create IPS card + snapshot (linked to clinic)
            card = IpsCard(
                patient_guid=patient.guid,
                clinic_guid=clinic.guid if clinic else None,
                title=f"IPS — {mp['given']} {mp['family']}",
                mode="full",
            )
            db.session.add(card)
            db.session.flush()

            now = datetime.now(timezone.utc)
            bundle = generate_ips_bundle(patient, mode="full", composition_date=now)
            snapshot = IpsSnapshot(
                card_guid=card.guid,
                bundle_json=bundle,
                composition_date=now,
                mode="full",
                resource_count=len(bundle.get("entry", [])),
            )
            db.session.add(snapshot)
        created_guids.append(patient.guid)
        created_count += 1

    db.session.commit()
    # #793: report euIPS conformance rather than listing resource types. The
    # operator's question is "are these valid patient summaries", and the old
    # message asserted a list of sections without checking any of them.
    conformant = 0
    for guid in created_guids:
        rows = (db.session.query(FhirResource)
                .filter(FhirResource.patient_guid == guid).all())
        if euips_sections.is_conformant(
                euips_sections.status_for_resources(rows)):
            conformant += 1
    detail = ("required sections only (skip_clinical)" if skip_clinical
              else "full euIPS section set")
    flash(
        f"Generated {created_count} patients for {org_name} — {detail}. "
        f"{conformant}/{created_count} carry all three euIPS required sections "
        f"(allergies, problems, medications) either as content or as an "
        f"explicit 'none known' statement.",
        "success" if conformant == created_count else "warning",
    )
    return redirect(url_for("admin.dashboard"))


# ── Documentation Routes ─────────────────────────────────────


def _now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _get_capability_statement():
    """Get the current CapabilityStatement (from DB or default)."""
    from app.models.capability_statement import CapabilityStatement
    cs = db.session.query(CapabilityStatement).filter_by(is_current=True).first()
    if cs:
        return cs.resource_json
    from app.fhir.fhir_routes import _default_capability_statement
    return _default_capability_statement()


def _downloadable(html_content, filename):
    """Wrap rendered HTML in a download response."""
    response = make_response(html_content)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.route("/docs")
def docs_index():
    """Documentation index page."""
    return render_template("docs_index.html")


@bp.route("/docs/api")
def docs_api():
    """API endpoint reference."""
    return render_template("docs_api.html", generated=_now_str())


@bp.route("/docs/api/download")
def docs_api_download():
    """Download API reference as standalone HTML."""
    html = render_template("docs_api.html", generated=_now_str())
    return _downloadable(html, "ips_api_reference.html")


@bp.route("/docs/capability")
def docs_capability():
    """FHIR CapabilityStatement viewer."""
    cs = _get_capability_statement()
    cs_json = json.dumps(cs, indent=2)
    return render_template("docs_capability.html", cs=cs, cs_json=cs_json)


@bp.route("/docs/capability/download")
def docs_capability_download():
    """Download Capability Statement as standalone HTML."""
    cs = _get_capability_statement()
    cs_json = json.dumps(cs, indent=2)
    html = render_template("docs_capability.html", cs=cs, cs_json=cs_json)
    return _downloadable(html, "ips_capability_statement.html")


@bp.route("/docs/manual")
def docs_manual():
    """Operator manual."""
    return render_template("docs_manual.html", generated=_now_str())


@bp.route("/docs/manual/download")
def docs_manual_download():
    """Download operator manual as standalone HTML."""
    html = render_template("docs_manual.html", generated=_now_str())
    return _downloadable(html, "ips_operator_manual.html")


@bp.route("/docs/technical")
def docs_technical():
    """Technical documentation."""
    return render_template("docs_technical.html", generated=_now_str())


@bp.route("/docs/technical/download")
def docs_technical_download():
    """Download technical docs as standalone HTML."""
    html = render_template("docs_technical.html", generated=_now_str())
    return _downloadable(html, "ips_technical_documentation.html")
