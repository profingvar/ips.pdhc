"""Authentication service — SSO token validation and API key checking."""

import hashlib
from datetime import datetime, timezone
from functools import wraps

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
            # Find or create local user record
            user = db.session.query(User).filter_by(
                username=user_info.get("username", "")
            ).first()
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
