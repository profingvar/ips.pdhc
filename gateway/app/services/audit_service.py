"""Audit logging service — records security-relevant events."""

import uuid

from flask import request, g

from app.models.base import db
from app.models.audit_log import AuditLog


#: The kinds of actor an audit row can name.
#:
#: `AuditLog.actor_type` is `String(32)`, nullable, with no CHECK and no enum.
#: Four values were in use across FIVE files as bare literals with no single
#: place to look — which is how a fifth kind, a machine, came to have no value
#: at all (#921). Listed here so the sixth is added deliberately.
#:
#: Only the first three are decided by this module. `patient` and `proxy` are
#: passed in directly by the patient and proxy surfaces, which know something
#: this function cannot: `app/patient_portal.py`, `api/patient_consents_routes.py`,
#: `api/patient_blocks_routes.py`, `api/patient_proxy_routes.py`. Those call
#: sites still use literals; bringing them here is a refactor #921 did not ask
#: for, and this comment is the record that the divergence was seen.
ACTOR_USER = "user"        # an authenticated human with a local users row
ACTOR_SYSTEM = "system"    # no actor in context: a CLI command, a scheduler
ACTOR_SERVICE = "service"  # a scoped, identity-less API key (#921)
ACTOR_PATIENT = "patient"  # set by the patient surface
ACTOR_PROXY = "proxy"      # set by the next-of-kin surface (#889)
ACTOR_TYPES = (ACTOR_USER, ACTOR_SYSTEM, ACTOR_SERVICE,
               ACTOR_PATIENT, ACTOR_PROXY)


def current_session_id() -> str | None:
    """Return the SSO session_id ("sid" JWT claim, see ticket #191)
    for the current request, or None if not available.

    Resolution order (ticket #203):
      1. ``X-Operator-Session-Id`` request header — canonical carrier
         for internal API-key callers (sim.pdhc / monitor.pdhc / etc.)
         that don't go through an SSO blob.
      2. ``g.access_blob['session_id']`` — set by ``require_auth`` on
         each fresh /me/service response.
      3. None — legacy caller / AUTH_DISABLED dev blob without the
         claim. Audit row gets NULL; downstream PDL kontroller queries
         must treat NULL as "no session correlation available".
    """
    try:
        header_val = request.headers.get("X-Operator-Session-Id")
    except RuntimeError:
        # No active request context (CLI / background work).
        header_val = None
    if header_val:
        return header_val[:128]
    blob = getattr(g, "access_blob", None)
    if isinstance(blob, dict):
        sid = blob.get("session_id")
        if sid:
            return str(sid)[:128]
    return None


def log_event(
    event_type: str,
    *,
    patient_guid: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_guid: uuid.UUID | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """Create an audit log entry from the current request context."""
    # #921: an identity-less service key was audited as a USER with a NULL
    # actor_guid. `_service_account_user` builds a TRANSIENT User for a
    # key-only caller — the right shape for authorisation, since it is
    # `is_superuser=False` — but this function classified the actor by
    # PRESENCE (`"user" if actor else "system"`), and a service account is
    # not None. So machine traffic was indistinguishable from a person's in
    # the one place Rule 24's full operation log exists to answer that, and
    # the row read `actor_type='user'` with `actor_guid=NULL`, a combination
    # that should not be reachable for a real user.
    #
    # The role is imported rather than re-spelled: `auth_service` owns it,
    # and a literal in two modules is a literal that drifts. Imported here
    # rather than at module scope because nothing else couples these two.
    from app.services.auth_service import SERVICE_ACCOUNT_ROLE

    actor = getattr(g, "current_user", None)
    api_key = getattr(g, "api_key", None)
    is_service = getattr(actor, "role", None) == SERVICE_ACCOUNT_ROLE

    # The transient User is never persisted, so it has no guid — which is
    # where the NULL came from. The KEY has one, `actor_guid` carries no
    # foreign key, and the api_keys row is what an incident responder would
    # actually want to look up.
    if is_service and api_key is not None:
        actor_guid = api_key.guid
    elif actor is not None:
        actor_guid = actor.guid
    else:
        actor_guid = None

    entry = AuditLog(
        actor_guid=actor_guid,
        actor_type=(ACTOR_SERVICE if is_service
                    else ACTOR_USER if actor else ACTOR_SYSTEM),
        actor_label=actor.display_name or actor.username if actor else "system",
        patient_guid=patient_guid,
        event_type=event_type,
        resource_type=resource_type,
        resource_guid=resource_guid,
        request_path=request.path if request else None,
        request_method=request.method if request else None,
        ip_address=request.remote_addr if request else None,
        session_id=current_session_id(),
        detail=detail or {},
    )
    db.session.add(entry)
    db.session.flush()
    return entry
