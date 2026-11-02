"""Authentication service — SSO token validation and API key checking."""

import hashlib
from datetime import datetime, timezone
from functools import wraps
from uuid import UUID

import httpx
from flask import request, g, jsonify, current_app

from app.models.base import db, utcnow
from app.models.user import User
from app.models.api_key import ApiKey


# Endpoints that don't require authentication
PUBLIC_ENDPOINTS = frozenset([
    "api_v1.health",
    "api_v1.metrics",
    "fhir_api.capability_statement",
])


def hash_api_key(raw_key: str) -> str:
    """Hash an API key with SHA-256."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def resolve_sso_user(token: str) -> dict | None:
    """Resolve a Bearer token via the SSO service. Returns user info or None."""
    base_url = current_app.config["OAUTH_BASE_URL"]
    client_id = current_app.config.get("SSO_CLIENT_ID", "")
    client_secret = current_app.config.get("SSO_CLIENT_SECRET", "")

    headers = {"Authorization": f"Bearer {token}"}

    # Use service endpoint when credentials are configured
    if client_id and client_secret:
        endpoint = f"{base_url}/api/auth/me/service"
        headers["X-SSO-Client-Id"] = client_id
        headers["X-SSO-Client-Secret"] = client_secret
    else:
        endpoint = f"{base_url}/api/auth/me"

    try:
        resp = httpx.get(endpoint, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError:
        pass
    return None


def validate_api_key(raw_key: str) -> ApiKey | None:
    """Validate an API key. Returns the ApiKey record or None."""
    key_hash = hash_api_key(raw_key)
    api_key = db.session.query(ApiKey).filter_by(key_hash=key_hash).first()
    if not api_key:
        return None
    if not api_key.is_active:
        return None
    if api_key.revoked_at:
        return None
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        return None
    # Update last_used_at
    api_key.last_used_at = utcnow()
    db.session.flush()
    return api_key


def require_auth(f):
    """Decorator to enforce authentication on a route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check if endpoint is public
        if request.endpoint in PUBLIC_ENDPOINTS:
            return f(*args, **kwargs)

        # Dev bypass
        if current_app.config.get("AUTH_DISABLED"):
            g.current_user = _synthetic_dev_user()
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return _auth_error("Missing Authorization header")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_info = resolve_sso_user(token)
            if not user_info:
                return _auth_error("Invalid or expired token")
            # Ticket #53 / SSO #43: block API calls while SSO requires a
            # password change. require_auth guards API+FHIR routes only;
            # HTML admin routes have their own before_request.
            mcp = _must_change_password_response(user_info)
            if mcp is not None:
                return mcp
            # Resolve the local user record. The SSO blob carries no
            # `username` field (it identifies by email), so the historical
            # username-only lookup could never match an SSO professional —
            # the bearer API path was dead for operators (found by the
            # 2026-07-10 kontroller chain demo). ips usernames are
            # email-shaped, so fall back to the blob email.
            ident = (user_info.get("username")
                     or user_info.get("email") or "")
            user = db.session.query(User).filter_by(
                username=ident).first()
            if not user:
                return _auth_error("User not found in local system")
            if not user.is_active:
                return _auth_error("User account is inactive")
            g.current_user = user
            # Ticket #203: stash the full SSO blob so downstream helpers
            # (audit_service.current_session_id) can read session_id
            # without revalidating the token.
            g.access_blob = user_info

        elif auth_header.startswith("ApiKey "):
            raw_key = auth_header[7:]
            api_key = validate_api_key(raw_key)
            if not api_key:
                return _auth_error("Invalid or expired API key")
            if api_key.user:
                g.current_user = api_key.user
            else:
                g.current_user = _service_account_user(api_key)
        else:
            return _auth_error("Unsupported authorization scheme")

        return f(*args, **kwargs)
    return decorated


def require_patient(f):
    """Decorator for the patient-portal surface (IPS Renov 3, #199).

    Distinct from ``require_auth``: the patient identity comes from the
    SSO access blob, not from a local IPS ``users`` row. A patient SSO
    blob carries ``user_type == 'patient'`` and a top-level
    ``patient_guid`` (see sso.pdhc auth_service.build_access_blob); we
    expose those on ``g.access_blob`` and ``g.patient_guid``.

    Auth failures are 401; user_type mismatch (e.g. a staff token hitting
    a patient-portal endpoint) is 403 so the operator and the caller can
    tell them apart in the logs.

    Dev mode (``AUTH_DISABLED``): if the request carries an
    ``X-Dev-Patient-Guid`` header, treat it as the authenticated patient.
    Tests use this; production never sets ``AUTH_DISABLED``.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get("AUTH_DISABLED"):
            dev_guid = request.headers.get("X-Dev-Patient-Guid")
            if not dev_guid:
                return _auth_error("X-Dev-Patient-Guid required in AUTH_DISABLED dev mode")
            g.access_blob = {
                "user_type": "patient",
                "patient_guid": dev_guid,
                "session_id": request.headers.get("X-Operator-Session-Id"),
            }
            g.patient_guid = dev_guid
            g.current_user = None
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return _auth_error("Missing Authorization header")
        if not auth_header.startswith("Bearer "):
            return _auth_error("Patient-portal endpoints require a Bearer token")

        token = auth_header[7:]
        blob = resolve_sso_user(token)
        if not blob:
            return _auth_error("Invalid or expired token")
        mcp = _must_change_password_response(blob)
        if mcp is not None:
            return mcp
        if blob.get("user_type") != "patient":
            return _auth_error(
                "This endpoint is reserved for patient-portal callers", 403
            )
        patient_guid = blob.get("patient_guid")
        if not patient_guid:
            # SSO blob missing patient_guid — usually a misconfigured
            # patient account on the SSO side, or a blob from a
            # pre-#188 SSO. Refuse rather than silently fall through.
            return _auth_error(
                "SSO blob is missing patient_guid", 403
            )
        g.access_blob = blob
        g.patient_guid = patient_guid
        g.current_user = None
        return f(*args, **kwargs)
    return decorated


def require_patient_html(f):
    """HTML-rendering counterpart of :func:`require_patient` (#245).

    Used by the patient-portal HTML routes under /patient/*. Differs
    from ``require_patient`` in three ways:

      - On failure, renders an HTML page (``patient_portal_denied.html``)
        instead of a JSON OperationOutcome.
      - In prod, the identity comes from the Flask session
        (``sso_token`` set by sso_routes.callback) — we then
        re-validate it against SSO on each request, per the standing
        ``/auth/me`` re-validation contract (CLAUDE.md §11). No
        cached blob.
      - Missing-session redirects to ``sso.login`` instead of returning
        401, so a logged-out browser lands on the login page cleanly.

    Dev mode (``AUTH_DISABLED``): ``session['dev_patient_guid']`` carries
    the identity. Tests set it via ``client.session_transaction()``.
    Falls back to the ``X-Dev-Patient-Guid`` header so API+HTML tests
    share fixtures.
    """
    from flask import redirect, render_template, session, url_for

    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get("AUTH_DISABLED"):
            dev_guid = (
                session.get("dev_patient_guid")
                or request.headers.get("X-Dev-Patient-Guid")
            )
            if not dev_guid:
                return render_template(
                    "patient_portal_denied.html",
                    message=(
                        "Dev mode: set session['dev_patient_guid'] or "
                        "send X-Dev-Patient-Guid header."
                    ),
                ), 401
            g.access_blob = {
                "user_type": "patient",
                "patient_guid": dev_guid,
                "session_id": None,
            }
            g.patient_guid = dev_guid
            g.current_user = None
            return f(*args, **kwargs)

        token = session.get("sso_token")
        if not token:
            session["sso_next"] = request.url
            return redirect(url_for("sso.login"))

        blob = resolve_sso_user(token)
        if not blob:
            session["sso_next"] = request.url
            return redirect(url_for("sso.login"))

        mcp = _must_change_password_response(blob)
        if mcp is not None:
            # In an HTML context, redirect the user to the
            # change-password page rather than returning a JSON
            # OperationOutcome.
            base = current_app.config.get("OAUTH_BASE_URL", "").rstrip("/")
            return redirect(f"{base}/change-password")

        if blob.get("user_type") != "patient":
            return render_template(
                "patient_portal_denied.html",
                message=(
                    "This is the patient portal. You're signed in as "
                    f"user_type={blob.get('user_type', '?')!r}."
                ),
            ), 403

        patient_guid = blob.get("patient_guid")
        if not patient_guid:
            return render_template(
                "patient_portal_denied.html",
                message="SSO blob is missing patient_guid.",
            ), 403

        g.access_blob = blob
        g.patient_guid = patient_guid
        g.current_user = None
        return f(*args, **kwargs)
    return decorated


def _auth_error(message: str, code: int = 401):
    """Return a FHIR-style OperationOutcome for auth failures."""
    return jsonify({
        "resourceType": "OperationOutcome",
        "issue": [{
            "severity": "error",
            "code": "security" if code == 401 else "forbidden",
            "diagnostics": message,
        }]
    }), code


def _must_change_password_response(blob: dict | None):
    """Uniform response when SSO flags `must_change_password=True`.

    require_auth is used on API/FHIR routes, so we return a 403
    OperationOutcome carrying the SSO change-password URL in the
    diagnostics. Returns None if no change required.
    """
    if not blob or not blob.get("must_change_password"):
        return None
    base = current_app.config.get("OAUTH_BASE_URL", "").rstrip("/")
    return jsonify({
        "resourceType": "OperationOutcome",
        "issue": [{
            "severity": "error",
            "code": "forbidden",
            "diagnostics": "Password change required before further actions",
            "details": {"text": f"{base}/change-password"},
        }]
    }), 403


def _synthetic_dev_user() -> User:
    """Create a transient dev user for AUTH_DISABLED mode."""
    user = User(
        username="dev-user",
        display_name="Development User",
        role="admin",
        is_active=True,
        is_superuser=True,
    )
    return user


def _service_account_user(api_key: ApiKey) -> User:
    """Create a transient user representation for key-only auth."""
    user = User(
        username=f"apikey:{api_key.prefix}",
        display_name=api_key.label or f"API Key {api_key.prefix}",
        role="service_account",
        is_active=True,
        is_superuser=False,
    )
    return user


# =====================================================================
# Proxy (next-of-kin) admission to the patient surface — EPS C3, #889.
# =====================================================================

# The subject patient a proxy claims to be acting for. A relative may
# hold grants from more than one patient (a parent of two children), so
# the subject cannot be derived from the identity alone.
PROXY_SUBJECT_HEADER = "X-Acting-For-Patient"

# Dev-mode headers, mirroring X-Dev-Patient-Guid above. Production never
# sets AUTH_DISABLED.
DEV_PROXY_HEADER = "X-Dev-Proxy-User-Guid"


def _proxy_grants_for(proxy_user_guid):
    """Every grant naming this proxy, in ANY state.

    Deliberately unfiltered: ``evaluate_proxy_access`` needs the revoked
    and not-yet-valid rows in order to tell "never granted" from "no
    longer granted" for the audit.
    """
    from app.models.patient_proxy_grant import PatientProxyGrant
    return (
        PatientProxyGrant.query
        .filter(PatientProxyGrant.proxy_user_guid == proxy_user_guid)
        .all()
    )


def _audit_proxy_decision(*, proxy_user_guid, patient_guid, allowed, reason):
    """Record the access DECISION — which happened whether or not the
    route then succeeds. Logging "a read occurred" from a decorator
    would be a claim about something that has not run yet.

    This COMMITS. Every other audit helper in this repo does
    ``add`` + ``flush`` and lets the route's own commit carry the row,
    but a proxy read is a GET and a GET commits nothing, so a flushed
    row would be rolled back at teardown — visible in a test fixture
    that shares the session, gone in production. That asymmetry has
    bitten this platform before.
    """
    from app.models.base import db
    from app.models.audit_log import AuditLog
    try:
        entry = AuditLog(
            # ACTOR is the relative; SUBJECT is the patient. Keeping
            # them apart is what makes a proxy read distinguishable
            # from the patient's own — the Lag (2022:913)
            # chain-of-custody requirement cited in sso's blob builder.
            actor_guid=UUID(str(proxy_user_guid)) if proxy_user_guid else None,
            actor_type="proxy",
            actor_label=f"proxy:{proxy_user_guid}",
            patient_guid=UUID(str(patient_guid)) if patient_guid else None,
            event_type=(
                "proxy_access_granted" if allowed else "proxy_access_refused"
            ),
            resource_type="PatientProxyGrant",
            request_path=request.path,
            request_method=request.method,
            ip_address=request.remote_addr,
            session_id=(
                g.access_blob.get("session_id")
                if isinstance(getattr(g, "access_blob", None), dict)
                else None
            ),
            detail={"mechanism": "patient_proxy", "reason": reason},
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        # An audit failure must not convert a correct refusal into a
        # 500, nor a correct grant into one. Roll back so the session is
        # usable for the route that follows.
        try:
            from app.models.base import db as _db
            _db.session.rollback()
        except Exception:
            pass


def require_patient_or_proxy(f):
    """Patient-portal surface, also admitting a patient-granted proxy.

    A patient is admitted exactly as :func:`require_patient` admits one —
    this decorator is a superset and changes nothing for them.

    A proxy (sso ``user_type == 'relative'``, #890) is admitted only when
    ALL of the following hold, decided by
    ``care_access_policy.evaluate_proxy_access``:

      - the request method is safe (GET/HEAD/OPTIONS). A proxy is
        read-only, and this is enforced HERE rather than per route,
        because per-route is how one gets missed. Ten of the seventeen
        routes behind the patient identity are POST, and they are the
        spärr and consent controls — a proxy able to POST could lift a
        spärr and then read what it was hiding.
      - an active ``PatientProxyGrant`` names this proxy for the subject
        patient, with *now* inside its validity interval.

    The subject patient comes from the ``X-Acting-For-Patient`` header,
    or is defaulted when the proxy holds exactly ONE active grant —
    mirroring sso's own "sole affiliation" rule, which defaults
    ``active_affiliation_guid`` when there is no ambiguity.

    On success ``g.patient_guid`` is the SUBJECT, so every existing
    patient-portal route works unchanged, while ``g.proxy_user_guid``
    and ``g.actor_type`` keep the acting identity available for audit.
    For a patient, ``g.proxy_user_guid`` is None and ``g.actor_type`` is
    ``'patient'``.

    Both proxy denial codes map to ONE response. Telling a caller "there
    was a grant but it is revoked" would confirm that this patient once
    named this person; the precise code goes to the audit only.
    """
    from app.services.care_access_policy import (
        evaluate_proxy_access, REASON_PROXY_WRITE_REFUSED,
    )

    @wraps(f)
    def decorated(*args, **kwargs):
        def _admit_patient(blob, patient_guid):
            g.access_blob = blob
            g.patient_guid = patient_guid
            g.proxy_user_guid = None
            g.actor_type = "patient"
            g.current_user = None
            return f(*args, **kwargs)

        def _admit_proxy(blob, proxy_user_guid):
            subject = request.headers.get(PROXY_SUBJECT_HEADER)
            grants = _proxy_grants_for(proxy_user_guid)

            if not subject:
                active = [gr for gr in grants if gr.is_active()]
                if len(active) == 1:
                    subject = str(active[0].patient_guid)
                elif len(active) > 1:
                    return _auth_error(
                        f"{PROXY_SUBJECT_HEADER} is required when acting for "
                        "more than one patient", 400,
                    )

            allowed, basis, reason = evaluate_proxy_access(
                patient_guid=subject,
                proxy_user_guid=proxy_user_guid,
                grants=grants,
                method=request.method,
            )
            _audit_proxy_decision(
                proxy_user_guid=proxy_user_guid,
                patient_guid=subject,
                allowed=allowed,
                reason=reason,
            )
            if not allowed:
                if reason == REASON_PROXY_WRITE_REFUSED:
                    return _auth_error(
                        "A next-of-kin proxy is read-only on this surface",
                        403,
                    )
                return _auth_error(
                    "No active next-of-kin grant for this patient", 403
                )

            g.access_blob = blob
            g.patient_guid = subject
            g.proxy_user_guid = proxy_user_guid
            g.actor_type = "proxy"
            g.access_basis = basis
            g.current_user = None
            return f(*args, **kwargs)

        if current_app.config.get("AUTH_DISABLED"):
            dev_proxy = request.headers.get(DEV_PROXY_HEADER)
            if dev_proxy:
                return _admit_proxy(
                    {
                        "user_type": "relative",
                        "user_guid": dev_proxy,
                        "session_id": request.headers.get(
                            "X-Operator-Session-Id"
                        ),
                    },
                    dev_proxy,
                )
            dev_guid = request.headers.get("X-Dev-Patient-Guid")
            if not dev_guid:
                return _auth_error(
                    f"X-Dev-Patient-Guid or {DEV_PROXY_HEADER} required in "
                    "AUTH_DISABLED dev mode"
                )
            return _admit_patient(
                {
                    "user_type": "patient",
                    "patient_guid": dev_guid,
                    "session_id": request.headers.get(
                        "X-Operator-Session-Id"
                    ),
                },
                dev_guid,
            )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return _auth_error("Missing Authorization header")
        if not auth_header.startswith("Bearer "):
            return _auth_error("Patient-portal endpoints require a Bearer token")

        blob = resolve_sso_user(auth_header[7:])
        if not blob:
            return _auth_error("Invalid or expired token")
        mcp = _must_change_password_response(blob)
        if mcp is not None:
            return mcp

        user_type = blob.get("user_type")

        if user_type == "patient":
            patient_guid = blob.get("patient_guid")
            if not patient_guid:
                return _auth_error("SSO blob is missing patient_guid", 403)
            return _admit_patient(blob, patient_guid)

        if user_type == "relative":
            proxy_user_guid = blob.get("user_guid")
            if not proxy_user_guid:
                # #890: the relative blob carries identity only. Without
                # user_guid there is nothing to match a grant against,
                # and guessing would be the fail-open direction.
                return _auth_error("SSO blob is missing user_guid", 403)
            return _admit_proxy(blob, proxy_user_guid)

        return _auth_error(
            "This endpoint is reserved for patient-portal callers", 403
        )

    return decorated


def require_proxy_self(f):
    """Admit a relative for acts on their OWN grant only — EPS A3 clause 4.

    Deliberately NOT a relaxation of :func:`require_patient_or_proxy`.
    That decorator refuses every non-safe method centrally because the
    patient surface behind it is the spärr and consent controls; adding
    a method exception there would reopen the hole it exists to close.
    This is a separate door that opens onto exactly one room.

    It sets ``g.proxy_user_guid`` and NOTHING else — in particular it
    does not set ``g.patient_guid``, so a route behind this decorator
    cannot accidentally read the patient surface. The route must scope
    its own lookup to ``g.proxy_user_guid``.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get("AUTH_DISABLED"):
            dev_proxy = request.headers.get(DEV_PROXY_HEADER)
            if not dev_proxy:
                return _auth_error(
                    f"{DEV_PROXY_HEADER} required in AUTH_DISABLED dev mode"
                )
            g.access_blob = {"user_type": "relative", "user_guid": dev_proxy}
            g.proxy_user_guid = dev_proxy
            g.actor_type = "proxy"
            g.patient_guid = None
            g.current_user = None
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return _auth_error("Missing Authorization header")
        if not auth_header.startswith("Bearer "):
            return _auth_error("Patient-portal endpoints require a Bearer token")

        blob = resolve_sso_user(auth_header[7:])
        if not blob:
            return _auth_error("Invalid or expired token")
        mcp = _must_change_password_response(blob)
        if mcp is not None:
            return mcp

        if blob.get("user_type") != "relative":
            return _auth_error(
                "This endpoint is reserved for next-of-kin callers", 403
            )
        proxy_user_guid = blob.get("user_guid")
        if not proxy_user_guid:
            return _auth_error("SSO blob is missing user_guid", 403)

        g.access_blob = blob
        g.proxy_user_guid = proxy_user_guid
        g.actor_type = "proxy"
        g.patient_guid = None
        g.current_user = None
        return f(*args, **kwargs)

    return decorated
