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
from app.services import (euips_batch, euips_eu_additions,
                          euips_header, euips_optional, euips_recommended,
                          euips_required, euips_sections)
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.services.ips_generator import generate_ips_bundle
from app.services.fhir_service import create_resource
from app.services.audit_service import log_event

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

#: #811: the columns the patient list can be ordered by, mapped to the model
#: attribute that actually sorts them.
#:
#: An ALLOWLIST, not `getattr(PatientIndex, request.args["sort"])` -- that
#: would let a query string reach any attribute on the model, and
#: `order_by` on the wrong one is at best a 500.
#:
#: `organisation` and `cards`/`resources` are deliberately absent: those three
#: columns are computed per row AFTER the query (a sub-count and a lookup into
#: the FHIR Patient resource), so there is nothing to ORDER BY. Offering a
#: header that sorted only the 100 fetched rows would be a worse answer than
#: not offering it -- see the note on LIST_LIMIT below.
PATIENT_SORTS = {
    "name": (PatientIndex.family_name, PatientIndex.given_name),
    "identifier": (PatientIndex.identifier_value,),
    "birth_date": (PatientIndex.birth_date,),
    "gender": (PatientIndex.gender,),
    "created": (PatientIndex.created_at,),
}

#: Unchanged from before #811. Stated as a constant because the sort is now
#: server-side BECAUSE of it: sorting in the browser would reorder the 100 rows
#: that happened to be fetched and present them as "the patients sorted by X",
#: which is wrong whenever more than 100 exist.
LIST_LIMIT = 100


@bp.route("/patients")
def patients():
    """Patient browser — search and list patients."""
    q = request.args.get("q", "").strip()

    # #811: default to newest first. Was family_name, which buries a cohort
    # that was just generated somewhere in the middle of the alphabet.
    sort = request.args.get("sort", "created")
    if sort not in PATIENT_SORTS:
        sort = "created"
    direction = "asc" if request.args.get("dir") == "asc" else "desc"

    # #811: archived patients are hidden from the list but NOT from search.
    # "Do not delete, retain searchability etc but do not list it" -- so a
    # name or identifier search still finds them (the template marks them),
    # and `?archived=1` shows the archived set on its own.
    show_archived = request.args.get("archived") == "1"

    query = db.session.query(PatientIndex)

    if show_archived:
        query = query.filter(PatientIndex.archived_at.isnot(None))
    elif not q:
        query = query.filter(PatientIndex.archived_at.is_(None))

    # #811: inspect one generation batch. This is what makes a batch more than
    # a row of counts -- before this there was no way to see WHICH patients a
    # batch created without reading the database by hand.
    batch = request.args.get("batch", "").strip()
    batch_invalid = False
    if batch:
        try:
            query = query.filter(
                PatientIndex.generation_batch_guid == uuid.UUID(batch))
        except (ValueError, TypeError):
            # A malformed guid must not 500 and must not silently return the
            # unfiltered list as though the filter had applied.
            batch_invalid = True
            query = query.filter(db.false())

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                PatientIndex.family_name.ilike(like_q),
                PatientIndex.given_name.ilike(like_q),
                PatientIndex.identifier_value.ilike(like_q),
            )
        )

    cols = PATIENT_SORTS[sort]
    query = query.order_by(*[
        c.desc().nullslast() if direction == "desc" else c.asc().nullslast()
        for c in cols
    ])

    total = query.count()
    patients_list = query.limit(LIST_LIMIT).all()

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
                           clinics=clinics, orgs=orgs,
                           # #797: so a batch can be seen and undone.
                           batches=euips_batch.list_batches(),
                           # #811: sort state, archive view, batch filter.
                           sort=sort, dir=direction,
                           show_archived=show_archived,
                           batch=batch, batch_invalid=batch_invalid,
                           total=total, limit=LIST_LIMIT,
                           archived_total=(
                               db.session.query(PatientIndex)
                               .filter(PatientIndex.archived_at.isnot(None))
                               .count()))


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


# ── Archive / unarchive (#811) ───────────────────────────────
#
# "Do not delete, retain searchability etc but do not list it."
#
# So this sets a timestamp and nothing else. It does NOT touch `is_active`
# (FHIR Patient.active, and already filtered by the cross-service roster
# endpoint sim.pdhc reads), does NOT delete anything, and does NOT change a
# single API response. An archived patient is still returned by
# GET /api/v1/patients/<guid>, still appears in its clinic's roster, still
# carries its blocks and consents. The only thing that changes is whether the
# default admin list shows the row.
#
# That restraint is the point: archiving is a VIEW decision taken by an
# operator tidying a table, and a view decision must not quietly become a
# clinical or an access-control one. Purge is the destructive action and is
# separate, deliberate, and shows its counts first.


def _set_patient_archived(guid, archived: bool):
    """Shared body for archive and unarchive. Returns the patient or aborts."""
    patient = db.session.get(PatientIndex, guid)
    if not patient:
        abort(404)
    patient.archived_at = datetime.now(timezone.utc) if archived else None
    # Rule 24: full operation log. Hiding a row from a list is still an
    # operator action on a patient record, and "where did that patient go"
    # has to be answerable from the audit log rather than from guesswork.
    #
    # log_event() BEFORE the commit, and ONE commit for both. `log_event` does
    # `add` + `flush` and deliberately does not commit -- it leaves that to the
    # caller, which is how all 32 call sites in this service work. Committing
    # the patient change first and logging after looks equivalent and is not:
    # the audit row is then flushed into a transaction nobody commits and is
    # discarded when the request ends. Found in production, where the archive
    # landed and the audit entry did not, after the SQLite test suite passed --
    # the test fixture's session keeps a flushed-but-uncommitted row visible to
    # the next query, so the assertion succeeded against a row that would never
    # exist. One commit also makes the state change and its audit record
    # atomic, which is the behaviour Rule 24 actually wants.
    log_event(
        "patient_archive" if archived else "patient_unarchive",
        patient_guid=patient.guid,
        resource_type="Patient",
        resource_guid=patient.guid,
        detail={"archived_at": (patient.archived_at.isoformat()
                                if patient.archived_at else None)},
    )
    db.session.commit()
    return patient


def _back_to_patients():
    """Return to the list the operator was looking at, not to its default.

    Archiving from a filtered or sorted view and landing back on page one of
    the default order loses the operator's place, which makes archiving a
    handful of rows needlessly tedious.
    """
    args = {k: v for k, v in request.form.items()
            if k in ("q", "sort", "dir", "archived", "batch") and v}
    return redirect(url_for("admin.patients", **args))


@bp.route("/patients/<uuid:guid>/archive", methods=["POST"])
def archive_patient(guid):
    """Hide a patient from the default admin list. Not a delete."""
    patient = _set_patient_archived(guid, True)
    flash(f"Archived {patient.family_name or ''}, {patient.given_name or ''} "
          f"— still searchable and still returned by the API.", "success")
    return _back_to_patients()


@bp.route("/patients/<uuid:guid>/unarchive", methods=["POST"])
def unarchive_patient(guid):
    """Put a patient back in the default list."""
    patient = _set_patient_archived(guid, False)
    flash(f"Restored {patient.family_name or ''}, "
          f"{patient.given_name or ''} to the list.", "success")
    return _back_to_patients()


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

# #795: `_mock_patient_resources` and `_OBSERVATIONS` are gone. Every euIPS
# section is now generated by a dedicated service module, in obligation order:
#
#   euips_required.py     the three REQUIRED sections    (#793)
#   euips_recommended.py  the four RECOMMENDED sections  (#794)
#   euips_optional.py     the seven OPTIONAL sections    (#795)
#
# Vital signs were the last thing left in the old helper. They moved because
# seven euIPS sections map to `Observation` and are told apart by `category` --
# the old helper emitted no category at all, so its observations were
# attributable to no section. See euips_sections.section_matches.


@bp.route("/mock-data/purge", methods=["POST"])
def purge_mock_batch():
    """#797 — delete a whole generation batch.

    Destructive, so the batch guid must be given explicitly: there is no
    "purge the last one" or "purge all", because either would make a mistake
    cheap to commit and expensive to notice. The patients page shows each
    batch's counts first, which is the same compare-then-write shape the
    deploy scripts use.
    """
    batch_guid = (request.form.get("batch_guid") or "").strip()
    removed = euips_batch.purge_batch(batch_guid)
    if removed is None:
        flash(f"No generation batch {batch_guid!r} — nothing was deleted.",
              "error")
    else:
        flash(
            f"Purged batch {removed['batch_guid']}: "
            f"{removed['patients']} patients, "
            f"{removed['clinical_resources']} clinical resources, "
            f"{removed['patient_resources']} Patient resources, "
            f"{removed['clinic_assignments']} clinic assignments.",
            "success")
    return redirect(url_for("admin.patients"))


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
    # #793 et al: the generation logic now lives in
    # app/services/mock_generator.py. It was inline here, reading
    # `request.form` and reporting through `flash()`, which made a browser
    # with an SSO session the ONLY way to generate patients — unusable from a
    # CLI or a verification script, which is exactly what rebuilding the
    # cohort needed. This route is now one caller of two; the web flow is
    # unchanged.
    from app.services import mock_generator

    clinic_guid = request.form.get("clinic_guid", "")
    count = int(request.form.get("count", "4"))
    skip_clinical = request.form.get("skip_clinical", "").lower() in {
        "on", "1", "true"}

    # #812: an AGE range, not birth years. Blank means the default span.
    try:
        r = mock_generator.generate(
            clinic_guid, count=count, skip_clinical=skip_clinical,
            age_min=request.form.get("age_min") or None,
            age_max=request.form.get("age_max") or None)
    except mock_generator.AgeRangeError as exc:
        # Surfaced, not clamped. A cohort generated for the wrong ages looks
        # exactly like one generated for the right ages, so there is no later
        # symptom to catch it.
        flash(f"Age range rejected: {exc}. No patients were created.", "error")
        return redirect(url_for("admin.patients"))

    detail = ("required sections only (skip_clinical)" if r["skip_clinical"]
              else "full euIPS section set")
    flash(
        f"Generated {r['created']} patients for {r['clinic_name']}, "
        f"ages {r['age_min']}\u2013{r['age_max']} — {detail}. "
        f"{r['conformant']}/{r['created']} carry all three euIPS required "
        f"sections (allergies, problems, medications) either as content or as "
        f"an explicit 'none known' statement. "
        f"{r['resources']} clinical resources. "
        f"Batch {r['batch_guid']} — inspectable and purgeable below.",
        "success" if r["conformant"] == r["created"] else "warning",
    )
    # #812: back to the patient list, where the batch can be Inspected —
    # the dashboard shows counts, not the cohort that was just created.
    return redirect(url_for("admin.patients"))


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
