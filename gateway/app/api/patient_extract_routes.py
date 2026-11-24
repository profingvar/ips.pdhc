"""GET /api/v1/patient-extract/<patient_guid> — eps's part of the record.pdhc
patient extract (#1059, plan s4.4, D9, D10).

The door is the loggkontroll one (`audit_routes.patient_access_log`, #1045):

  * `require_auth_or_care_bearer`: the professional's OWN SSO bearer,
    re-validated with sso on every request. A patient's bearer is 401
    (842540c: it never maps to an eps users row and is not a professional);
  * an `ApiKey` caller is refused 403 `bearer_required`: no service key gets
    an extract;
  * then `patient_export.exportable` (Rule 24, the same scope as `/state`)
    AND D9 (`patient_extract.d9_allows`: SU, or a doctor/nurse affiliated to
    an active unit where the patient is actively listed). Out of scope
    answers the SAME 404 as "no such patient", never an empty extract.

Every call is audited as `patient_extract` with `detail.outcome`
(`served` / `denied` / `not_found`), refusals included.
"""
from flask import Blueprint, current_app, g, jsonify

from app.models.base import db
from app.models.patient_index import PatientIndex
from app.services.auth_service import require_auth_or_care_bearer
from app.services.guids import is_uuid

bp = Blueprint("patient_extract_api", __name__, url_prefix="/api/v1/patient-extract")

EVENT = "patient_extract"
_NOT_FOUND = {"error": "patient not found"}


def _audit(guid, outcome, **detail):
    from app.services.audit_service import log_event
    import uuid as _uuid
    log_event(EVENT, patient_guid=_uuid.UUID(guid) if guid else None,
              detail={"outcome": outcome, **detail})
    db.session.commit()


@bp.route("/<guid>", methods=["GET"])
@require_auth_or_care_bearer
def patient_extract(guid):
    from app.services import patient_export as px
    from app.services import patient_extract as ex

    valid = is_uuid(guid)
    guid = guid.lower() if valid else guid
    if not current_app.config.get("AUTH_DISABLED") and \
            getattr(g, "bearer_blob", None) is None:
        _audit(guid if valid else None, "denied", reason="bearer_required")
        return jsonify({"error": "bearer_required",
                        "message": "a patient extract is taken out with a "
                                   "person's own SSO bearer, not a service key"}), 403
    if not valid:
        _audit(None, "denied", reason="malformed_guid")
        return jsonify({"error": "malformed patient guid"}), 400

    pi = db.session.query(PatientIndex).filter_by(guid=guid).first()
    if pi is None:
        _audit(guid, "not_found", reason="no_such_patient")
        return jsonify(_NOT_FOUND), 404
    try:
        allowed, _ = px.exportable([guid])
        ok = guid in allowed and ex.d9_allows(guid, getattr(g, "bearer_blob", None))
    except Exception:  # noqa: BLE001 — fail closed
        db.session.rollback()
        ok = False
    if not ok:
        _audit(guid, "denied", reason="out_of_scope")
        return jsonify(_NOT_FOUND), 404

    body = ex.build(pi)
    _audit(guid, "served", n_sections=len(body["sections"]),
           n_items=sum(s["count"] for s in body["sections"]))
    return jsonify(body)
