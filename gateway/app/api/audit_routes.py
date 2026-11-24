"""Audit log query endpoints.

    GET /api/v1/audit                      the whole log, filtered; SU only
    GET /api/v1/audit/patients/<guid>      ONE patient's access log (#1045)

#1045 (loggkontroll, patientdatalagen 4 kap. 3 §): dashboard.pdhc merges the
access logs of the services that hold a patient's data into one list. This
module's part is eps's own log, `audit_log`, for one patient.

THE GATE of the per-patient read is a PERSON's, never a machine's:

  * `require_auth_or_care_bearer`: the professional's own SSO bearer,
    re-validated with sso on every request (never cached);
  * an `ApiKey` caller is refused 403 `bearer_required`: a key names no
    person, and a service key is organisation-blind (Rule 24) — a log of who
    saw a patient is not something a machine reads on its own behalf;
  * then `patient_export.exportable`, the SAME "may this reader see this
    patient" as `/state` and `/clinics`: SU = every patient; a professional =
    patients actively listed at a clinic of their affiliated care units
    (`affiliations[].care_unit_guid`, never `organization_ids`). Out of scope
    answers the same 404 as "no such patient", so probing learns nothing.

The read of the log is itself logged (`patient.access_log.read`), and so is a
refusal for a patient that exists (`patient.access_log.refused`).

`GET /api/v1/audit` was `require_auth` only: any eps users row and any API key
could read every patient's audit rows, organisation-blind. No service calls
it (checked over `git ls-files` of every repo, 2026-11-24); it is now SU only.
"""

from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request

from app.models.base import db
from app.models.audit_log import AuditLog
from app.models.patient_index import PatientIndex
from app.services.auth_service import require_auth, require_auth_or_care_bearer
from app.services.guids import is_uuid

bp = Blueprint("audit_api", __name__, url_prefix="/api/v1/audit")

#: The per-patient read's page size: default and hard maximum.
PATIENT_LOG_DEFAULT_LIMIT = 1000
PATIENT_LOG_MAX_LIMIT = 5000

#: `detail` keys handed out by the per-patient read. Metadata only: the
#: audit `detail` of some events carries more than a log reviewer needs.
_DETAIL_KEYS = ("reason", "outcome", "format", "mode", "access_basis",
                "refusal_code", "scope")


@bp.route("", methods=["GET"])
@require_auth
def query_audit():
    """Query audit events with filters. SU only (#1045)."""
    from app.services import patient_export as px
    if not px.is_admin():
        return jsonify({"error": "forbidden",
                        "message": "the whole audit log is for SU admins; "
                                   "use /api/v1/audit/patients/<guid>"}), 403
    query = db.session.query(AuditLog)

    actor_guid = request.args.get("actor_guid")
    patient_guid = request.args.get("patient_guid")
    event_type = request.args.get("event_type")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    limit = min(int(request.args.get("limit", 100)), 1000)

    if actor_guid:
        query = query.filter_by(actor_guid=actor_guid)
    if patient_guid:
        query = query.filter_by(patient_guid=patient_guid)
    if event_type:
        query = query.filter_by(event_type=event_type)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            query = query.filter(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            query = query.filter(AuditLog.created_at <= dt)
        except ValueError:
            pass

    events = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in events])


def _instant(name: str):
    """(datetime | None, error | None) for an ISO-8601 query argument. A
    naive value is read as UTC."""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None, None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, f"{name} is not an ISO-8601 instant: {raw!r}"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt, None


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def access_item(row: AuditLog) -> dict:
    """One row in the platform's access-log shape (#1045, the same keys in
    every service; dashboard.pdhc/app/services/access_log.py reads them)."""
    detail = row.detail if isinstance(row.detail, dict) else {}
    kept = {k: str(detail[k])[:200] for k in _DETAIL_KEYS if detail.get(k) is not None}
    refused = row.event_type.endswith(("_refused", ".refused", ".denied"))
    return {
        "id": str(row.guid),
        "at": _iso(row.created_at),
        "user_guid": str(row.actor_guid) if row.actor_guid else None,
        "user_label": row.actor_label,
        "actor_type": row.actor_type,
        "action": row.event_type,
        "outcome": "denied" if refused else (kept.get("outcome") or "served"),
        "route": (f"{row.request_method or ''} {row.request_path or ''}".strip()
                  or None),
        "resource_type": row.resource_type,
        "session_id": row.session_id,
        # eps does not record the reader's care units on the row.
        "actor_units": None,
        "basis": kept.get("access_basis"),
        "detail": kept,
    }


@bp.route("/patients/<guid>", methods=["GET"])
@require_auth_or_care_bearer
def patient_access_log(guid):
    """Who read or changed this patient's data in eps, and when (#1045).

    ?from=<ISO>  ?to=<ISO> (exclusive)  ?limit=<n, default 1000, max 5000>
    Oldest first. `truncated` says when there were more rows than `limit`.
    """
    from app.services import patient_export as px
    from app.services.audit_service import log_event

    if not current_app.config.get("AUTH_DISABLED") and \
            getattr(g, "bearer_blob", None) is None:
        return jsonify({"error": "bearer_required",
                        "message": "a patient's access log is read with a "
                                   "person's own SSO bearer, not a service key"}), 403
    if not is_uuid(guid):
        return jsonify({"error": "malformed patient guid"}), 400
    guid = guid.lower()
    since, err1 = _instant("from")
    until, err2 = _instant("to")
    if err1 or err2:
        return jsonify({"error": err1 or err2}), 400
    try:
        limit = int(request.args.get("limit", PATIENT_LOG_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return jsonify({"error": "limit is not a number"}), 400
    limit = max(1, min(PATIENT_LOG_MAX_LIMIT, limit))

    try:
        allowed, _ = px.exportable([guid])
    except Exception:  # noqa: BLE001 — fail closed
        allowed = []
    if guid not in allowed:
        exists = db.session.query(PatientIndex.guid).filter_by(guid=guid).first()
        if exists:
            log_event("patient.access_log.refused", patient_guid=guid,
                      detail={"reason": "out_of_scope"})
            db.session.commit()
        return jsonify({"error": "patient not found"}), 404

    q = db.session.query(AuditLog).filter(AuditLog.patient_guid == guid)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at < until)
    total = q.count()
    rows = q.order_by(AuditLog.created_at.asc()).limit(limit).all()
    items = [access_item(r) for r in rows]

    log_event("patient.access_log.read", patient_guid=guid,
              detail={"n_rows": len(items), "from": _iso(since), "to": _iso(until)})
    db.session.commit()
    return jsonify({"service": "eps.pdhc", "patient_guid": guid,
                    "from": _iso(since), "to": _iso(until),
                    "items": items, "total": total, "limit": limit,
                    "truncated": total > len(items)})
