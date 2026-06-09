"""Admin HTML form for indispensable-care block lift — ticket #244.

UI half of #201 (which shipped the API at POST /api/v1/admin/blocks/
<guid>/lift). A clinician can't reasonably be asked to curl a JSON
body when the legal mechanical filter — concept_guids + from_date +
until_date — is what protects them under PDL Ch 4 § 5. This form
makes those fields explicit and previews exactly what the patient
notification will look like before the lift commits.

Three pages, mounted on the existing ``admin`` blueprint (so the
SSO session check at the top of admin.py applies here too):

    GET  /admin/blocks/<block_guid>/lift          — form
    POST /admin/blocks/<block_guid>/lift/confirm  — confirmation
                                                    (no commit yet)
    POST /admin/blocks/<block_guid>/lift/submit   — actually lifts
                                                    and writes the
                                                    audit row
    GET  /admin/blocks/<block_guid>/lift/done     — success screen

Role gate mirrors :mod:`app.api.admin_blocks_routes`: SU admin always
passes; otherwise the local-user role must be in the configured
``IPS_INDISPENSABLE_LIFT_ROLES`` set (default ``{'physician',
'admin'}``). Refusal renders an explicit 403 page that names the
runbook so a denied caller knows where to ask for the role.

The confirmation screen renders the patient notification template
(``sparr_copy.json`` → ``indispensable_care_notification``) with
real placeholder fill so the clinician sees the exact wording the
patient will read. Required per the runbook (§5) and helps a
reviewer evaluate the form during #241 clinical sign-off without
needing to know how the notification copy works internally.
"""
from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID

from flask import (
    abort, current_app, flash, redirect, render_template, request,
    session, url_for,
)

from app.admin import bp as admin_bp
from app.models.base import db, utcnow
from app.models.clinic import Clinic
from app.models.patient_block import PatientBlock
from app.models.patient_index import PatientIndex
from app.models.user import User
from app.services.audit_service import log_event
from app.services.block_webhook import safe_dispatch as _emit_block_webhook
from app.services.sparr_copy import section as _sparr_section


# Same default the API uses (24 h).
DEFAULT_INDISPENSABLE_LIFT_SECONDS = 24 * 60 * 60


# ---------------------------------------------------------------------------
# Role gating
# ---------------------------------------------------------------------------

def _allowed_lift_roles() -> set:
    raw = (
        current_app.config.get("IPS_INDISPENSABLE_LIFT_ROLES")
        or os.environ.get("IPS_INDISPENSABLE_LIFT_ROLES")
        or "physician,admin"
    )
    return {r.strip() for r in raw.split(",") if r.strip()}


def _current_user_for_session():
    """Resolve the SSO session blob to a local User row.

    Returns ``(user, source)`` where ``source`` is ``"sso"`` when the
    user came from the session blob, ``"dev"`` in AUTH_DISABLED mode.
    Returns ``(None, None)`` if no plausible identity is available.
    """
    if current_app.config.get("AUTH_DISABLED"):
        # Dev mode: synthesise an SU user matching the API path.
        u = User(
            username="dev-admin",
            display_name="Development User",
            role="admin",
            is_active=True,
            is_superuser=True,
        )
        return u, "dev"
    sso_user = session.get("sso_user") or {}
    email = sso_user.get("email")
    if not email:
        return None, None
    user = db.session.query(User).filter_by(email=email).first()
    return user, "sso"


def _can_lift(user) -> bool:
    if user is None:
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", "") in _allowed_lift_roles()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_or_404(block_guid):
    try:
        block_guid_obj = UUID(str(block_guid))
    except (ValueError, TypeError):
        abort(404)
    block = (
        db.session.query(PatientBlock)
        .filter_by(guid=block_guid_obj)
        .first()
    )
    if block is None:
        abort(404)
    return block


def _patient_label(patient: PatientIndex) -> str:
    """Display name for the lift form — family, given OR identifier
    fallback. We deliberately do NOT include the personnummer
    plain-text; the form shows enough for the clinician to confirm
    the right patient but no more than that.
    """
    parts = []
    if patient.family_name:
        parts.append(patient.family_name)
    if patient.given_name:
        parts.append(patient.given_name)
    if parts:
        return ", ".join(parts)
    return f"Patient/{patient.guid}"


def _scope_label(block: PatientBlock) -> str:
    if block.source_scope_type == "clinic":
        clinic = db.session.query(Clinic).filter_by(
            guid=block.source_scope_id
        ).first()
        if clinic:
            return f"{clinic.name} (clinic)"
    return f"{block.source_scope_type} {block.source_scope_id}"


def _parse_iso_opt(s):
    """Lenient ISO parser, returns (dt, error)."""
    from datetime import datetime as _dt
    if not s:
        return None, None
    if not isinstance(s, str):
        return None, "expected ISO 8601 string"
    try:
        return _dt.fromisoformat(s.replace("Z", "+00:00")), None
    except ValueError:
        return None, "must be ISO 8601 (e.g. 2026-06-09T12:00:00Z)"


def _split_concept_guids(raw: str) -> tuple[list[str], str | None]:
    """One-per-line textarea → list of validated UUID strings."""
    if not raw:
        return [], None
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            out.append(str(UUID(s)))
        except (ValueError, TypeError):
            return [], f"not a valid UUID: {s!r}"
    return out, None


def _build_notification_preview(
    block, *, reason, concept_guids, from_date, until_date,
    lift_expires_at, caregiver_label,
):
    """Fill the indispensable_care_notification template (sv) with
    the form values so the confirmation screen shows what the patient
    will read. Returns the rendered string."""
    sect = _sparr_section("indispensable_care_notification", "sv")
    body = (sect or {}).get("body", "")
    if not body:
        return "(notification template not available)"
    # The runbook acceptance is that the clinician sees the FORM-FILLED
    # template, not a generic "would have rendered something" message.
    return body.format(
        caregiver_name=caregiver_label,
        accessed_at="(at lift time)",
        reason=reason,
        concept_summary=(
            f"{len(concept_guids)} concept(s)"
            if concept_guids else "(none)"
        ),
        from_date=from_date or "(any)",
        until_date=until_date or "(any)",
        expires_at=(
            lift_expires_at.strftime("%Y-%m-%d %H:%M UTC")
            if lift_expires_at else "(default 24h)"
        ),
        audit_link="(audit link generated after submit)",
        caregiver_contact="(see your caregiver's contact directory)",
    )


# ---------------------------------------------------------------------------
# Form (GET)
# ---------------------------------------------------------------------------

@admin_bp.route("/blocks/<block_guid>/lift", methods=["GET"])
def block_lift_form(block_guid):
    user, _src = _current_user_for_session()
    if not _can_lift(user):
        return render_template(
            "admin_block_lift_denied.html",
            allowed_roles=", ".join(sorted(_allowed_lift_roles())),
        ), 403

    block = _block_or_404(block_guid)
    if not block.is_active():
        flash(
            "This block is already lifted — nothing to do here.",
            "warning",
        )
        return redirect(url_for("admin.dashboard"))

    patient = db.session.get(PatientIndex, block.patient_guid)
    if patient is None:
        abort(404)

    return render_template(
        "admin_block_lift_form.html",
        block=block,
        patient_label=_patient_label(patient),
        scope_label=_scope_label(block),
        default_expires_in_hours=24,
    )


# ---------------------------------------------------------------------------
# Confirmation (POST, no commit yet)
# ---------------------------------------------------------------------------

@admin_bp.route("/blocks/<block_guid>/lift/confirm", methods=["POST"])
def block_lift_confirm(block_guid):
    user, _src = _current_user_for_session()
    if not _can_lift(user):
        return render_template(
            "admin_block_lift_denied.html",
            allowed_roles=", ".join(sorted(_allowed_lift_roles())),
        ), 403

    block = _block_or_404(block_guid)
    if not block.is_active():
        flash("Block is already lifted.", "warning")
        return redirect(url_for("admin.dashboard"))

    reason = (request.form.get("reason") or "").strip()
    concept_guids_raw = request.form.get("concept_guids") or ""
    expires_in_h_raw = (
        request.form.get("expires_in_hours") or "24"
    ).strip()
    from_date_raw = (request.form.get("from_date") or "").strip()
    until_date_raw = (request.form.get("until_date") or "").strip()

    errors = []
    if not reason:
        errors.append("Reason is required (PDL Ch 4 § 5 mandates written justification).")
    concept_guids, ce = _split_concept_guids(concept_guids_raw)
    if ce:
        errors.append(f"Concept GUIDs: {ce}")
    elif not concept_guids:
        errors.append(
            "At least one concept GUID is required (mechanical filter — legal 2026-06-04)."
        )

    try:
        expires_in_h = int(expires_in_h_raw)
        if expires_in_h <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Expires in (hours) must be a positive integer.")
        expires_in_h = 24

    from_dt, fe = _parse_iso_opt(from_date_raw)
    if fe:
        errors.append(f"From date: {fe}")
    until_dt, ue = _parse_iso_opt(until_date_raw)
    if ue:
        errors.append(f"Until date: {ue}")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("admin.block_lift_form", block_guid=block_guid))

    patient = db.session.get(PatientIndex, block.patient_guid)
    if patient is None:
        abort(404)
    lift_expires_at = utcnow() + timedelta(hours=expires_in_h)

    preview = _build_notification_preview(
        block,
        reason=reason,
        concept_guids=concept_guids,
        from_date=from_date_raw,
        until_date=until_date_raw,
        lift_expires_at=lift_expires_at,
        caregiver_label=_scope_label(block),
    )

    return render_template(
        "admin_block_lift_confirm.html",
        block=block,
        patient_label=_patient_label(patient),
        scope_label=_scope_label(block),
        reason=reason,
        concept_guids=concept_guids,
        concept_guids_raw=concept_guids_raw,
        expires_in_hours=expires_in_h,
        from_date_raw=from_date_raw,
        until_date_raw=until_date_raw,
        projected_lift_expires_at=lift_expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        notification_preview=preview,
    )


# ---------------------------------------------------------------------------
# Submit (POST, commits)
# ---------------------------------------------------------------------------

@admin_bp.route("/blocks/<block_guid>/lift/submit", methods=["POST"])
def block_lift_submit(block_guid):
    user, _src = _current_user_for_session()
    if not _can_lift(user):
        return render_template(
            "admin_block_lift_denied.html",
            allowed_roles=", ".join(sorted(_allowed_lift_roles())),
        ), 403

    block = _block_or_404(block_guid)
    if not block.is_active():
        flash("Block is already lifted.", "warning")
        return redirect(url_for("admin.dashboard"))

    reason = (request.form.get("reason") or "").strip()
    concept_guids_raw = request.form.get("concept_guids") or ""
    expires_in_h_raw = (
        request.form.get("expires_in_hours") or "24"
    ).strip()
    from_date_raw = (request.form.get("from_date") or "").strip()
    until_date_raw = (request.form.get("until_date") or "").strip()

    # Re-validate at submit (defensive — the confirm screen could have
    # been bypassed by a hand-crafted POST).
    if not reason:
        flash("Reason is required.", "error")
        return redirect(url_for("admin.block_lift_form", block_guid=block_guid))
    concept_guids, ce = _split_concept_guids(concept_guids_raw)
    if ce or not concept_guids:
        flash("At least one valid concept GUID is required.", "error")
        return redirect(url_for("admin.block_lift_form", block_guid=block_guid))
    try:
        expires_in_h = int(expires_in_h_raw)
        if expires_in_h <= 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Expires in (hours) must be a positive integer.", "error")
        return redirect(url_for("admin.block_lift_form", block_guid=block_guid))
    from_dt, fe = _parse_iso_opt(from_date_raw)
    if fe:
        flash(f"From date: {fe}", "error")
        return redirect(url_for("admin.block_lift_form", block_guid=block_guid))
    until_dt, ue = _parse_iso_opt(until_date_raw)
    if ue:
        flash(f"Until date: {ue}", "error")
        return redirect(url_for("admin.block_lift_form", block_guid=block_guid))

    now = utcnow()
    block.lifted_at = now
    block.lifted_by_user_guid = getattr(user, "guid", None)
    block.lifted_reason = reason
    block.lift_kind = "indispensable_care"
    block.lift_concept_guids = concept_guids
    block.lift_expires_at = now + timedelta(hours=expires_in_h)
    block.lift_from_date = from_dt
    block.lift_until_date = until_dt
    db.session.flush()

    actor_guid = getattr(user, "guid", None)
    audit = log_event(
        event_type="block.lifted",
        patient_guid=block.patient_guid,
        resource_type="PatientBlock",
        resource_guid=block.guid,
        detail={
            "lift_kind": "indispensable_care",
            "mechanism": "indispensable_care",
            "actor_user_guid": (
                str(actor_guid) if actor_guid else None
            ),
            "reason": reason,
            "lift_expires_at": (
                block.lift_expires_at.isoformat()
                if block.lift_expires_at else None
            ),
            "lift_concept_guids": block.lift_concept_guids,
            "lift_from_date": (
                block.lift_from_date.isoformat()
                if block.lift_from_date else None
            ),
            "lift_until_date": (
                block.lift_until_date.isoformat()
                if block.lift_until_date else None
            ),
            "admin_route": True,
            "ui": "html_form",  # distinguishes HTML form from raw API call
        },
    )
    db.session.commit()
    _emit_block_webhook("block.lifted", block)

    return redirect(url_for(
        "admin.block_lift_done",
        block_guid=block_guid,
        audit_guid=str(audit.guid),
    ))


# ---------------------------------------------------------------------------
# Success screen
# ---------------------------------------------------------------------------

@admin_bp.route("/blocks/<block_guid>/lift/done", methods=["GET"])
def block_lift_done(block_guid):
    user, _src = _current_user_for_session()
    if not _can_lift(user):
        return render_template(
            "admin_block_lift_denied.html",
            allowed_roles=", ".join(sorted(_allowed_lift_roles())),
        ), 403

    block = _block_or_404(block_guid)
    audit_guid = request.args.get("audit_guid") or ""
    return render_template(
        "admin_block_lift_done.html",
        block=block,
        scope_label=_scope_label(block),
        audit_guid=audit_guid,
    )
