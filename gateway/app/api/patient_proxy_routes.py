"""Patient-managed next-of-kin grants — EPS C3 (#889).

The patient's own surface for granting, listing and revoking a proxy
privilege, plus the one narrow route a proxy may use on itself.

WHO MAY DO WHAT, ratified by the operator in EPS A3 (#879) and enforced
through ``care_access_policy.proxy_mutation_allowed`` rather than by
ad-hoc checks here:

    both parties may REDUCE access; only the patient may INCREASE it

So ``POST ""`` (create) and the patient's revoke sit behind
``require_patient``. The proxy's own revoke sits behind
``require_proxy_self``, a deliberately narrow decorator that admits a
relative for exactly this one act and gives no access to the patient
surface. That is EPS A3's fourth clause: somebody who no longer wishes
to hold access to another person's record must be able to put it down
without asking the patient to act.

Why this is not simply an exception in ``require_patient_or_proxy``: that
decorator refuses every non-safe method centrally, on purpose, because
ten of the seventeen routes behind the patient identity are POST and
they are the spärr and consent controls. Punching a method exception
through it would reopen exactly the hole it exists to close. A separate
route with a separate decorator cannot widen that surface by accident.
"""

from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.models.base import db, utcnow
from app.models.patient_index import PatientIndex
from app.models.patient_proxy_grant import (
    PatientProxyGrant, PROXY_SCOPES, PROXY_GRANTED_VIA,
    SCOPE_READ_AS_PATIENT, ENDED_BY_PATIENT, ENDED_BY_PROXY,
)
from app.services.auth_service import require_patient, require_proxy_self
from app.services.care_access_policy import proxy_mutation_allowed

bp = Blueprint(
    "patient_proxy_api", __name__,
    url_prefix="/api/v1/patient/proxy-grants",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bad(message, code=400, extra=None):
    body = {"error": message}
    if extra:
        body.update(extra)
    return jsonify(body), code


def _patient_or_404(patient_guid):
    try:
        guid_obj = UUID(str(patient_guid))
    except (ValueError, TypeError):
        return None
    return db.session.query(PatientIndex).filter_by(guid=guid_obj).first()


def _parse_dt(raw, field):
    """Parse an ISO-8601 instant, or return (None, error_response)."""
    if raw in (None, ""):
        return None, None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")), None
    except (ValueError, TypeError):
        return None, _bad(f"{field} must be an ISO-8601 instant")


def _proxy_audit(event_type, *, grant, actor_guid, actor_type,
                 detail_extra=None):
    base = {
        "mechanism": "patient_proxy",
        "grant_guid": str(grant.guid),
        "proxy_user_guid": str(grant.proxy_user_guid),
    }
    if detail_extra:
        base.update(detail_extra)

    from app.models.audit_log import AuditLog
    entry = AuditLog(
        actor_guid=UUID(str(actor_guid)) if actor_guid else None,
        actor_type=actor_type,
        actor_label=f"{actor_type}:{actor_guid}",
        patient_guid=UUID(str(grant.patient_guid)),
        event_type=event_type,
        resource_type="PatientProxyGrant",
        resource_guid=grant.guid,
        request_path=request.path,
        request_method=request.method,
        ip_address=request.remote_addr,
        session_id=(
            g.access_blob.get("session_id")
            if isinstance(getattr(g, "access_blob", None), dict)
            else None
        ),
        detail=base,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


# ---------------------------------------------------------------------------
# GET — the patient lists their own grants
# ---------------------------------------------------------------------------

@bp.route("", methods=["GET"])
@require_patient
def list_own_grants():
    patient = _patient_or_404(g.patient_guid)
    if patient is None:
        return _bad("Patient record not found in IPS", 404)

    active_only = request.args.get("active", "false").lower() in (
        "1", "true", "yes",
    )
    rows = (
        PatientProxyGrant.query
        .filter(PatientProxyGrant.patient_guid == patient.guid)
        .order_by(PatientProxyGrant.granted_at.desc())
        .all()
    )
    if active_only:
        rows = [r for r in rows if r.is_active()]
    return jsonify({
        "patient_guid": str(patient.guid),
        "count": len(rows),
        "grants": [r.to_dict() for r in rows],
    }), 200


# ---------------------------------------------------------------------------
# POST — the patient grants a privilege. ONLY the patient (A3).
# ---------------------------------------------------------------------------

@bp.route("", methods=["POST"])
@require_patient
def create_grant():
    if not proxy_mutation_allowed(actor_role="patient", mutation="create"):
        # Unreachable via require_patient today; asserted so that the
        # policy stays the authority even if the decorator changes.
        return _bad("Only the patient may create a proxy grant", 403)

    patient = _patient_or_404(g.patient_guid)
    if patient is None:
        return _bad("Patient record not found in IPS", 404)

    data = request.get_json(silent=True) or {}

    raw_proxy = (data.get("proxy_user_guid") or "").strip()
    if not raw_proxy:
        return _bad("proxy_user_guid is required")
    try:
        proxy_guid = UUID(raw_proxy)
    except (ValueError, TypeError):
        return _bad("proxy_user_guid must be a GUID")

    scope = (data.get("scope") or SCOPE_READ_AS_PATIENT).strip()
    if scope not in PROXY_SCOPES:
        return _bad(
            "scope must be one of: " + ", ".join(PROXY_SCOPES),
            extra={"allowed_scopes": list(PROXY_SCOPES)},
        )

    granted_via = (data.get("granted_via") or "portal").strip()
    if granted_via not in PROXY_GRANTED_VIA:
        return _bad("granted_via must be one of: " + ", ".join(PROXY_GRANTED_VIA))

    valid_from, err = _parse_dt(data.get("valid_from"), "valid_from")
    if err:
        return err
    valid_to, err = _parse_dt(data.get("valid_to"), "valid_to")
    if err:
        return err
    if valid_from and valid_to and valid_to <= valid_from:
        return _bad("valid_to must be after valid_from")

    # "Only one ACTIVE grant per (patient, proxy)" — enforced here and
    # not by a database UNIQUE, because a UNIQUE over the pair would
    # make revocation terminal for that pair for ever (#891).
    existing = (
        PatientProxyGrant.query
        .filter(
            PatientProxyGrant.patient_guid == patient.guid,
            PatientProxyGrant.proxy_user_guid == proxy_guid,
        )
        .all()
    )
    if any(r.is_active() for r in existing):
        return _bad(
            "An active grant already exists for this person; revoke it "
            "before granting again", 409,
        )

    grant = PatientProxyGrant(
        patient_guid=patient.guid,
        proxy_user_guid=proxy_guid,
        proxy_label=(data.get("proxy_label") or None),
        scope=scope,
        valid_from=valid_from or utcnow(),
        valid_to=valid_to,
        granted_by_user_guid=UUID(str(g.patient_guid)),
        granted_via=granted_via,
        granted_note=(data.get("granted_note") or None),
    )
    db.session.add(grant)
    db.session.flush()
    _proxy_audit(
        "proxy_grant_created", grant=grant,
        actor_guid=g.patient_guid, actor_type="patient",
        detail_extra={"scope": scope, "granted_via": granted_via},
    )
    db.session.commit()
    return jsonify(grant.to_dict()), 201


# ---------------------------------------------------------------------------
# POST revoke — the PATIENT ends a grant.
# ---------------------------------------------------------------------------

@bp.route("/<grant_guid>/revoke", methods=["POST"])
@require_patient
def revoke_grant(grant_guid):
    if not proxy_mutation_allowed(actor_role="patient", mutation="revoke"):
        return _bad("Not permitted", 403)

    try:
        guid_obj = UUID(str(grant_guid))
    except (ValueError, TypeError):
        return _bad("grant_guid must be a GUID", 404)

    grant = PatientProxyGrant.query.filter_by(guid=guid_obj).first()
    # Scoped to the acting patient: a grant belonging to somebody else
    # is reported ABSENT, not refused, so a caller learns nothing about
    # guids that are not theirs.
    if grant is None or str(grant.patient_guid) != str(g.patient_guid):
        return _bad("Grant not found", 404)

    if grant.revoked_at is not None:
        return jsonify(grant.to_dict()), 200  # idempotent

    data = request.get_json(silent=True) or {}
    grant.revoked_at = utcnow()
    grant.revoked_by_user_guid = UUID(str(g.patient_guid))
    grant.revoked_by_role = ENDED_BY_PATIENT
    grant.revoked_reason = (data.get("reason") or None)
    _proxy_audit(
        "proxy_grant_revoked", grant=grant,
        actor_guid=g.patient_guid, actor_type="patient",
        detail_extra={"revoked_by_role": ENDED_BY_PATIENT},
    )
    db.session.commit()
    return jsonify(grant.to_dict()), 200


# ---------------------------------------------------------------------------
# POST revoke-own — the PROXY ends their own access (A3, clause 4).
#
# The only write a relative may perform anywhere in ips, and it can only
# ever REDUCE access.
# ---------------------------------------------------------------------------

@bp.route("/mine/<grant_guid>/revoke", methods=["POST"])
@require_proxy_self
def revoke_own_grant(grant_guid):
    if not proxy_mutation_allowed(actor_role="proxy", mutation="revoke"):
        return _bad("Not permitted", 403)

    try:
        guid_obj = UUID(str(grant_guid))
    except (ValueError, TypeError):
        return _bad("grant_guid must be a GUID", 404)

    grant = PatientProxyGrant.query.filter_by(guid=guid_obj).first()
    # Must name THIS proxy. Anything else is absent, not refused.
    if grant is None or str(grant.proxy_user_guid) != str(g.proxy_user_guid):
        return _bad("Grant not found", 404)

    if grant.revoked_at is not None:
        return jsonify(grant.to_dict()), 200  # idempotent

    data = request.get_json(silent=True) or {}
    grant.revoked_at = utcnow()
    grant.revoked_by_user_guid = UUID(str(g.proxy_user_guid))
    grant.revoked_by_role = ENDED_BY_PROXY
    grant.revoked_reason = (data.get("reason") or None)
    _proxy_audit(
        "proxy_grant_revoked", grant=grant,
        actor_guid=g.proxy_user_guid, actor_type="proxy",
        detail_extra={"revoked_by_role": ENDED_BY_PROXY},
    )
    db.session.commit()
    return jsonify(grant.to_dict()), 200
