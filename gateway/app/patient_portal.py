"""Patient-portal HTML pages — ticket #245.

Renders the JSON surfaces from #199 (PatientBlock) + #200 (PatientConsent)
into Jinja templates that the patient can drive from a browser. Pulls
the user-facing copy from the #210 bundle server-side via
:mod:`app.services.sparr_copy` (vs. fetching client-side from
``/api/v1/patient/copy/sparr`` — equivalent effect, simpler template
code, single source of truth).

Pages:

    GET   /patient/blocks                    — list own blocks
    POST  /patient/blocks/create             — block a source
    GET   /patient/blocks/<guid>/lift        — confirm consent-lift
    POST  /patient/blocks/<guid>/lift        — submit consent-lift
    GET   /patient/blocks/<guid>/extend      — extend form
    POST  /patient/blocks/<guid>/extend      — submit extend
    GET   /patient/consents                  — list + grant form
    POST  /patient/consents/create           — grant a consent
    GET   /patient/consents/<guid>/revoke    — confirm revoke
    POST  /patient/consents/<guid>/revoke    — submit revoke

Banners at the top of every page:

  - **legal_review_status banner** when the copy bundle hasn't been
    legally cleared (``is_legally_approved() == False``). Pinned by
    #210; production should gate on this.
  - **Indispensable-care notification banner** when at least one
    of the patient's blocks has an active ``lift_kind='indispensable_care'``
    lift. Renders the ``indispensable_care_notification`` template (sv)
    with the audit link so the patient sees the access the moment
    they open the portal.

Auth: :func:`require_patient_html`. Cross-patient block_guid in the
URL is the same confused-deputy guard as the API — render the 404
page without distinguishing "wrong patient" from "no such block".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request,
    url_for,
)

from app.models.base import db, utcnow
from app.models.clinic import Clinic
from app.models.patient_block import PatientBlock, BLOCK_SCOPE_TYPES
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientIndex
from app.services.auth_service import require_patient_html
from app.services.block_webhook import safe_dispatch as _emit_block_webhook
from app.services.sparr_copy import (
    is_legally_approved as _copy_approved,
    metadata as _copy_metadata,
    section as _copy_section,
)


bp = Blueprint(
    "patient_portal", __name__, url_prefix="/patient",
    template_folder="templates",
)


# Status labels — keyed by (is_active, lift_kind) so the patient sees
# plain-language state at a glance. Per ticket: "Aktiv / Hävd /
# Utgången / Tillfälligt tillgänglig vid oundgänglig vård".
def _block_status_label(block: PatientBlock) -> str:
    if block.lifted_at is not None and block.lift_kind == "consent":
        return "Hävd"
    if (
        block.lifted_at is not None
        and block.lift_kind == "indispensable_care"
        and block.lift_expires_at is not None
        and block.lift_expires_at.tzinfo is not None
        and block.lift_expires_at > datetime.now(timezone.utc)
    ):
        return "Tillfälligt tillgänglig vid oundgänglig vård"
    if (
        block.lifted_at is not None
        and block.lift_kind == "indispensable_care"
        and block.lift_expires_at is not None
        and block.lift_expires_at.tzinfo is None
        and block.lift_expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        return "Tillfälligt tillgänglig vid oundgänglig vård"
    if (
        block.expires_at is not None
        and not block.is_active()
    ):
        return "Utgången"
    if block.is_active():
        return "Aktiv"
    return "Hävd"


def _block_status_class(block: PatientBlock) -> str:
    label = _block_status_label(block)
    return {
        "Aktiv": "badge-info",
        "Hävd": "badge-success",
        "Utgången": "badge-warning",
        "Tillfälligt tillgänglig vid oundgänglig vård": "badge-danger",
    }.get(label, "badge-info")


# ---------------------------------------------------------------------------
# Common page context
# ---------------------------------------------------------------------------

def _patient_or_abort_404():
    try:
        guid_obj = UUID(str(g.patient_guid))
    except (ValueError, TypeError):
        abort(404)
    patient = db.session.query(PatientIndex).filter_by(guid=guid_obj).first()
    if patient is None:
        abort(404)
    return patient


def _safe_audit_url(block_guid):
    try:
        return url_for(
            "audit_api.list_audit_logs",
            resource_guid=str(block_guid),
        )
    except Exception:
        return "#"


def _page_context(patient: PatientIndex) -> dict:
    """Common context every patient-portal page needs."""
    md = _copy_metadata()
    banner = None
    rows = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=patient.guid)
        .all()
    )
    now = datetime.now(timezone.utc)
    active_indisp = []
    for r in rows:
        if r.lifted_at is None or r.lift_kind != "indispensable_care":
            continue
        exp = r.lift_expires_at
        if exp is None:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            continue
        active_indisp.append((exp, r))
    if active_indisp:
        active_indisp.sort(key=lambda t: t[0], reverse=True)
        _, block = active_indisp[0]
        sect = _copy_section("indispensable_care_notification", "sv")
        body_template = (sect or {}).get("body", "")
        caregiver_label = _scope_label_for(block)
        body = body_template.format(
            caregiver_name=caregiver_label,
            accessed_at=(
                block.lifted_at.strftime("%Y-%m-%d %H:%M UTC")
                if block.lifted_at else "?"
            ),
            reason=block.lifted_reason or "—",
            concept_summary=f"{len(block.lift_concept_guids or [])} concept(s)",
            from_date=(
                block.lift_from_date.strftime("%Y-%m-%d")
                if block.lift_from_date else "—"
            ),
            until_date=(
                block.lift_until_date.strftime("%Y-%m-%d")
                if block.lift_until_date else "—"
            ),
            expires_at=(
                block.lift_expires_at.strftime("%Y-%m-%d %H:%M UTC")
                if block.lift_expires_at else "?"
            ),
            audit_link=_safe_audit_url(block.guid),
            caregiver_contact="—",
        )
        banner = {
            "subject": (sect or {}).get("subject", "Indispensable-care access"),
            "body": body,
            "block_guid": str(block.guid),
        }
    return {
        "copy_metadata": md,
        "copy_approved": _copy_approved(),
        "indispensable_banner": banner,
        "patient": patient,
    }


def _scope_label_for(block: PatientBlock) -> str:
    if block.source_scope_type == "clinic":
        clinic = db.session.query(Clinic).filter_by(
            guid=block.source_scope_id
        ).first()
        if clinic:
            return clinic.name
    return f"{block.source_scope_type} {block.source_scope_id}"


# ---------------------------------------------------------------------------
# Blocks — list + create
# ---------------------------------------------------------------------------

@bp.route("/blocks", methods=["GET"])
@require_patient_html
def blocks_list():
    patient = _patient_or_abort_404()
    rows = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=patient.guid)
        .order_by(PatientBlock.created_at.desc())
        .all()
    )
    items = []
    for r in rows:
        items.append({
            "guid": str(r.guid),
            "source_scope_name": _scope_label_for(r),
            "status_label": _block_status_label(r),
            "status_class": _block_status_class(r),
            "created_at": r.created_at,
            "expires_at": r.expires_at,
            "is_active": r.is_active(),
            "lift_kind": r.lift_kind,
        })
    clinics = (
        db.session.query(Clinic)
        .filter_by(is_active=True)
        .order_by(Clinic.name)
        .all()
    )
    ctx = _page_context(patient)
    ctx.update({
        "blocks": items,
        "clinics": clinics,
        "block_create_copy": _copy_section("block_create_confirmation", "sv"),
        "block_list_copy": _copy_section("block_list", "sv"),
    })
    return render_template("patient_blocks.html", **ctx)


@bp.route("/blocks/create", methods=["POST"])
@require_patient_html
def blocks_create():
    patient = _patient_or_abort_404()
    scope_id_raw = (request.form.get("source_scope_id") or "").strip()
    reason = (request.form.get("reason") or "").strip() or None
    expires_at_raw = (request.form.get("expires_at") or "").strip()

    if not scope_id_raw:
        flash("Du måste välja en mottagning att spärra.", "error")
        return redirect(url_for("patient_portal.blocks_list"))
    try:
        scope_id = UUID(scope_id_raw)
    except (ValueError, TypeError):
        flash("Ogiltigt scope-ID.", "error")
        return redirect(url_for("patient_portal.blocks_list"))

    clinic = db.session.query(Clinic).filter_by(guid=scope_id).first()
    if clinic is None:
        flash("Mottagningen kunde inte hittas.", "error")
        return redirect(url_for("patient_portal.blocks_list"))

    expires_at = None
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(
                expires_at_raw.replace("Z", "+00:00")
            )
        except ValueError:
            flash("Ogiltigt förfallodatum (använd YYYY-MM-DD).", "error")
            return redirect(url_for("patient_portal.blocks_list"))

    existing = (
        db.session.query(PatientBlock)
        .filter_by(patient_guid=patient.guid, source_scope_id=scope_id)
        .all()
    )
    for row in existing:
        if row.is_active():
            flash(
                "Du har redan en aktiv spärr för den mottagningen.",
                "warning",
            )
            return redirect(url_for("patient_portal.blocks_list"))

    block = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type="clinic",
        source_scope_id=scope_id,
        created_by_user_guid=patient.guid,
        created_reason=reason,
        expires_at=expires_at,
    )
    db.session.add(block)
    db.session.flush()

    from app.models.audit_log import AuditLog
    db.session.add(AuditLog(
        actor_guid=patient.guid,
        actor_type="patient",
        actor_label=f"patient:{patient.guid}",
        patient_guid=patient.guid,
        event_type="block.created",
        resource_type="PatientBlock",
        resource_guid=block.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        detail={
            "mechanism": "consent",
            "block_guid": str(block.guid),
            "source_scope_type": "clinic",
            "source_scope_id": str(scope_id),
            "reason": reason,
            "ui": "patient_portal_html",
        },
    ))
    db.session.commit()
    _emit_block_webhook("block.created", block)
    flash(f"Spärr av {clinic.name} skapad.", "success")
    return redirect(url_for("patient_portal.blocks_list"))


# ---------------------------------------------------------------------------
# Lift (consent)
# ---------------------------------------------------------------------------

def _own_block_or_404(block_guid):
    try:
        block_guid_obj = UUID(str(block_guid))
    except (ValueError, TypeError):
        abort(404)
    block = (
        db.session.query(PatientBlock)
        .filter_by(guid=block_guid_obj, patient_guid=UUID(str(g.patient_guid)))
        .first()
    )
    if block is None:
        abort(404)
    return block


@bp.route("/blocks/<block_guid>/lift", methods=["GET"])
@require_patient_html
def block_lift_form(block_guid):
    patient = _patient_or_abort_404()
    block = _own_block_or_404(block_guid)
    if not block.is_active():
        flash("Den spärren är redan hävd.", "warning")
        return redirect(url_for("patient_portal.blocks_list"))
    ctx = _page_context(patient)
    ctx.update({
        "block": block,
        "scope_label": _scope_label_for(block),
    })
    return render_template("patient_block_lift.html", **ctx)


@bp.route("/blocks/<block_guid>/lift", methods=["POST"])
@require_patient_html
def block_lift_submit(block_guid):
    patient = _patient_or_abort_404()
    block = _own_block_or_404(block_guid)
    if not block.is_active():
        flash("Den spärren är redan hävd.", "warning")
        return redirect(url_for("patient_portal.blocks_list"))

    reason = (request.form.get("reason") or "").strip() or None

    block.lifted_at = utcnow()
    block.lifted_by_user_guid = patient.guid
    block.lifted_reason = reason
    block.lift_kind = "consent"
    block.lift_concept_guids = None
    block.lift_from_date = None
    block.lift_until_date = None
    block.lift_expires_at = None
    db.session.flush()

    from app.models.audit_log import AuditLog
    db.session.add(AuditLog(
        actor_guid=patient.guid,
        actor_type="patient",
        actor_label=f"patient:{patient.guid}",
        patient_guid=patient.guid,
        event_type="block.lifted",
        resource_type="PatientBlock",
        resource_guid=block.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        detail={
            "mechanism": "consent",
            "lift_kind": "consent",
            "block_guid": str(block.guid),
            "reason": reason,
            "ui": "patient_portal_html",
        },
    ))
    db.session.commit()
    _emit_block_webhook("block.lifted", block)
    flash("Spärr hävd.", "success")
    return redirect(url_for("patient_portal.blocks_list"))


# ---------------------------------------------------------------------------
# Extend
# ---------------------------------------------------------------------------

@bp.route("/blocks/<block_guid>/extend", methods=["GET"])
@require_patient_html
def block_extend_form(block_guid):
    patient = _patient_or_abort_404()
    block = _own_block_or_404(block_guid)
    if not block.is_active():
        flash("Den spärren kan inte förlängas (hävd eller utgången).", "warning")
        return redirect(url_for("patient_portal.blocks_list"))
    ctx = _page_context(patient)
    ctx.update({
        "block": block,
        "scope_label": _scope_label_for(block),
    })
    return render_template("patient_block_extend.html", **ctx)


@bp.route("/blocks/<block_guid>/extend", methods=["POST"])
@require_patient_html
def block_extend_submit(block_guid):
    patient = _patient_or_abort_404()
    block = _own_block_or_404(block_guid)
    if not block.is_active():
        flash("Den spärren kan inte förlängas.", "warning")
        return redirect(url_for("patient_portal.blocks_list"))

    quick_days_raw = (request.form.get("quick_days") or "").strip()
    expires_at_raw = (request.form.get("expires_at") or "").strip()

    new_expires_at = None
    if quick_days_raw:
        try:
            n = int(quick_days_raw)
            if n <= 0:
                raise ValueError
        except (TypeError, ValueError):
            flash("Ogiltigt antal dagar.", "error")
            return redirect(url_for(
                "patient_portal.block_extend_form",
                block_guid=block_guid,
            ))
        anchor = block.expires_at or utcnow()
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        new_expires_at = anchor + timedelta(days=n)
    elif expires_at_raw:
        try:
            new_expires_at = datetime.fromisoformat(
                expires_at_raw.replace("Z", "+00:00")
            )
        except ValueError:
            flash("Ogiltigt datum.", "error")
            return redirect(url_for(
                "patient_portal.block_extend_form",
                block_guid=block_guid,
            ))
    else:
        flash("Välj antal dagar eller ange ett datum.", "error")
        return redirect(url_for(
            "patient_portal.block_extend_form",
            block_guid=block_guid,
        ))

    if new_expires_at <= utcnow():
        flash(
            "Förfallodatumet måste ligga i framtiden — för att häva "
            "spärren, använd Häv-knappen.",
            "error",
        )
        return redirect(url_for(
            "patient_portal.block_extend_form",
            block_guid=block_guid,
        ))

    prev = block.expires_at
    block.expires_at = new_expires_at
    db.session.flush()

    from app.models.audit_log import AuditLog
    db.session.add(AuditLog(
        actor_guid=patient.guid,
        actor_type="patient",
        actor_label=f"patient:{patient.guid}",
        patient_guid=patient.guid,
        event_type="block.extended",
        resource_type="PatientBlock",
        resource_guid=block.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        detail={
            "mechanism": "consent",
            "block_guid": str(block.guid),
            "previous_expires_at": prev.isoformat() if prev else None,
            "new_expires_at": new_expires_at.isoformat(),
            "ui": "patient_portal_html",
        },
    ))
    db.session.commit()
    _emit_block_webhook("block.extended", block)
    flash("Spärrens förfallodatum förlängdes.", "success")
    return redirect(url_for("patient_portal.blocks_list"))


# ---------------------------------------------------------------------------
# Consents — list + grant
# ---------------------------------------------------------------------------

@bp.route("/consents", methods=["GET"])
@require_patient_html
def consents_list():
    patient = _patient_or_abort_404()
    rows = (
        db.session.query(PatientConsent)
        .filter_by(patient_guid=patient.guid)
        .order_by(PatientConsent.granted_at.desc())
        .all()
    )
    items = [r.to_dict() for r in rows]
    ctx = _page_context(patient)
    ctx.update({
        "consents": items,
    })
    return render_template("patient_consents.html", **ctx)


@bp.route("/consents/create", methods=["POST"])
@require_patient_html
def consents_create():
    patient = _patient_or_abort_404()
    grantee_raw = (request.form.get("grantee_caregiver_guid") or "").strip()
    note = (request.form.get("granted_note") or "").strip() or None
    expires_at_raw = (request.form.get("expires_at") or "").strip()

    if not grantee_raw:
        flash("Du måste ange vårdgivare.", "error")
        return redirect(url_for("patient_portal.consents_list"))
    try:
        grantee = UUID(grantee_raw)
    except (ValueError, TypeError):
        flash("Ogiltigt vårdgivare-GUID.", "error")
        return redirect(url_for("patient_portal.consents_list"))

    expires_at = None
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(
                expires_at_raw.replace("Z", "+00:00")
            )
        except ValueError:
            flash("Ogiltigt datum.", "error")
            return redirect(url_for("patient_portal.consents_list"))

    existing = (
        db.session.query(PatientConsent)
        .filter_by(
            patient_guid=patient.guid,
            grantee_caregiver_guid=grantee,
        )
        .all()
    )
    for row in existing:
        if row.is_active():
            flash(
                "Du har redan ett aktivt samtycke till den vårdgivaren.",
                "warning",
            )
            return redirect(url_for("patient_portal.consents_list"))

    consent = PatientConsent(
        patient_guid=patient.guid,
        grantee_caregiver_guid=grantee,
        granted_via="portal",
        granted_by_user_guid=patient.guid,
        granted_note=note,
        expires_at=expires_at,
    )
    db.session.add(consent)
    db.session.flush()

    from app.models.audit_log import AuditLog
    db.session.add(AuditLog(
        actor_guid=patient.guid,
        actor_type="patient",
        actor_label=f"patient:{patient.guid}",
        patient_guid=patient.guid,
        event_type="consent.granted",
        resource_type="PatientConsent",
        resource_guid=consent.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        detail={
            "mechanism": "consent",
            "consent_guid": str(consent.guid),
            "grantee_caregiver_guid": str(grantee),
            "ui": "patient_portal_html",
        },
    ))
    db.session.commit()
    flash("Samtycke registrerat.", "success")
    return redirect(url_for("patient_portal.consents_list"))


@bp.route("/consents/<consent_guid>/revoke", methods=["GET"])
@require_patient_html
def consent_revoke_form(consent_guid):
    patient = _patient_or_abort_404()
    try:
        consent_guid_obj = UUID(str(consent_guid))
    except (ValueError, TypeError):
        abort(404)
    consent = (
        db.session.query(PatientConsent)
        .filter_by(guid=consent_guid_obj, patient_guid=patient.guid)
        .first()
    )
    if consent is None:
        abort(404)
    if not consent.is_active():
        flash("Det samtycket är redan återkallat.", "warning")
        return redirect(url_for("patient_portal.consents_list"))
    ctx = _page_context(patient)
    ctx.update({"consent": consent})
    return render_template("patient_consent_revoke.html", **ctx)


@bp.route("/consents/<consent_guid>/revoke", methods=["POST"])
@require_patient_html
def consent_revoke_submit(consent_guid):
    patient = _patient_or_abort_404()
    try:
        consent_guid_obj = UUID(str(consent_guid))
    except (ValueError, TypeError):
        abort(404)
    consent = (
        db.session.query(PatientConsent)
        .filter_by(guid=consent_guid_obj, patient_guid=patient.guid)
        .first()
    )
    if consent is None:
        abort(404)
    if not consent.is_active():
        flash("Samtycket är redan återkallat.", "warning")
        return redirect(url_for("patient_portal.consents_list"))

    reason = (request.form.get("reason") or "").strip() or None
    consent.revoked_at = utcnow()
    consent.revoked_by_user_guid = patient.guid
    consent.revoked_reason = reason
    db.session.flush()

    from app.models.audit_log import AuditLog
    db.session.add(AuditLog(
        actor_guid=patient.guid,
        actor_type="patient",
        actor_label=f"patient:{patient.guid}",
        patient_guid=patient.guid,
        event_type="consent.revoked",
        resource_type="PatientConsent",
        resource_guid=consent.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        detail={
            "mechanism": "consent",
            "consent_guid": str(consent.guid),
            "grantee_caregiver_guid": str(consent.grantee_caregiver_guid),
            "reason": reason,
            "ui": "patient_portal_html",
        },
    ))
    db.session.commit()
    flash("Samtycket återkallat.", "success")
    return redirect(url_for("patient_portal.consents_list"))
