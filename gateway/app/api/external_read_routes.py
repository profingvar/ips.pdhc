"""External read door on ips: de-identified IPS data under a read grant.

The ips twin of cdr.pdhc's `/external/v1` (2026-11-19). An SU admin issues a
READ GRANT in sso.pdhc naming target "ips" among its targets; the partner
sends it as `Authorization: Bearer rg.<guid>.<secret>` to

    GET /external/v1/patients            patients of the grant's organisations
    GET /external/v1/patients/<guid>     one patient's de-identified summary

sso is asked about the key on EVERY request (no cache), with ips's own SSO
client pair, so revoke and expiry take effect at once.

Scope, in order:
  * organisations: patients with an ACTIVE clinic assignment to a clinic whose
    sso organisation is EXACTLY one of the grant's (operator decision: exact
    match, the same rule the CDRs apply to `patient_org_guid`);
  * consent: `consent_policy.evaluate_patient` with the grant's own purpose
    and research projects -- the same function behind /analysis-filter, so ips
    has one consent rule, not two.

What is returned is app/services/external_summary.summarise: GUID, sex, birth
year, coded diagnoses and medications. Never a name, personnummer or date of
birth.
"""
from __future__ import annotations

import uuid

import httpx
from flask import Blueprint, current_app, g, jsonify, request

from app.models.base import db
from app.models.clinic import Clinic
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.services import external_summary as ext
from app.services.consent_policy import evaluate_patient
from app.services.guids import is_uuid
from app.services.service_identity import sso_client_pair

bp = Blueprint("external_read", __name__, url_prefix="/external/v1")

TARGET = "ips"
TIMEOUT = 8
MAX_PATIENTS = 5000


def _refuse(status, error, message, **extra):
    return jsonify({"error": error, "message": message, **extra}), status


@bp.before_request
def _gate():
    auth = request.headers.get("Authorization", "")
    key = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if not key.startswith("rg."):
        return _refuse(401, "unauthenticated", "Send a read key as 'Authorization: Bearer rg.…'")
    base = (current_app.config.get("OAUTH_BASE_URL") or "").rstrip("/")
    cid, sec = sso_client_pair()  # #1017: by request host
    if not (base and cid and sec):
        return _refuse(503, "not_configured", "ips cannot check read keys (SSO not configured)")
    try:
        r = httpx.post(f"{base}/api/internal/read-grants/validate",
                          json={"key": key, "cdr": TARGET},
                          headers={"X-SSO-Client-Id": cid, "X-SSO-Client-Secret": sec},
                          timeout=TIMEOUT)
    except httpx.HTTPError:
        current_app.logger.warning("external read: sso unreachable")
        return _refuse(503, "sso_unavailable", "The read key could not be checked; try again")
    if r.status_code == 401:
        return _refuse(401, "invalid_key", "Unknown or wrong read key")
    if r.status_code == 403:
        try:
            reason = (r.json() or {}).get("reason")
        except ValueError:
            reason = None
        if reason:
            return _refuse(403, "forbidden", f"Read key refused: {reason}", reason=reason)
    if r.status_code != 200:
        current_app.logger.error("external read: sso validate answered %s", r.status_code)
        return _refuse(503, "sso_error", "The read key could not be checked")
    grant = r.json()
    if not grant.get("purpose_code"):
        return _refuse(403, "forbidden", "Read key has no purpose", reason="no_purpose")
    g.read_grant = grant
    return None


def _audit(event, **detail):
    from app.services.audit_service import log_event
    try:
        log_event(event, detail={"grant_guid": g.read_grant.get("grant_guid"),
                                 "partner_guid": g.read_grant.get("partner_guid"),
                                 "purpose": g.read_grant.get("purpose_code"), **detail})
    except Exception:  # noqa: BLE001 -- audit must not break the read
        current_app.logger.exception("external read audit failed")


def _in_scope(patient_guid=None) -> list[str]:
    """Patient guids in the grant's organisations that consent allows."""
    orgs = list(g.read_grant.get("org_guids") or [])
    if not orgs:
        return []
    q = (PatientClinicAssignment.active_only(
            db.session.query(PatientIndex)
            .join(PatientClinicAssignment, PatientClinicAssignment.patient_guid == PatientIndex.guid))
         .join(Clinic, Clinic.guid == PatientClinicAssignment.clinic_guid)
         .filter(Clinic.organisation_guid.in_(orgs), PatientIndex.is_active.is_(True)))
    if patient_guid is not None:
        q = q.filter(PatientIndex.guid == uuid.UUID(str(patient_guid)))
    purpose = g.read_grant["purpose_code"]
    projects = g.read_grant.get("research_project_guids") or []
    out = []
    for p in q.distinct().all():
        ok, _ = evaluate_patient({"ehds_opt_out": p.ehds_opt_out,
                                  "quality_registry_opt_out": p.quality_registry_opt_out,
                                  "consented_research_projects": p.consented_research_projects or []},
                                 purpose, projects)
        if ok:
            out.append(str(p.guid))
    return sorted(out)


@bp.get("/patients")
def list_patients():
    guids = _in_scope()
    truncated = len(guids) > MAX_PATIENTS
    guids = guids[:MAX_PATIENTS]
    _audit("external_read_list", n_returned=len(guids))
    return jsonify({"source": TARGET, "expires_at": g.read_grant.get("expires_at"),
                    "purpose": g.read_grant.get("purpose_code"),
                    "count": len(guids), "truncated": truncated, "patients": guids})


@bp.get("/patients/<guid>")
def get_patient(guid):
    if not is_uuid(guid) or not _in_scope(guid):
        _audit("external_read_patient", patient_guid=str(guid), n_returned=0)
        # Same answer for absent, outside the grant, or not consented.
        return _refuse(404, "not_found", "No such patient under this read key")
    out = ext.summarise([guid])
    _audit("external_read_patient", patient_guid=str(guid), n_returned=len(out))
    return jsonify({"source": TARGET, "patient": out[0] if out else None})
