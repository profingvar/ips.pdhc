"""SSO login/callback/logout routes for browser-based auth."""

import secrets
import logging

import httpx
from flask import (
    Blueprint, redirect, request, session, url_for, current_app, abort,
)

bp = Blueprint("sso", __name__)
logger = logging.getLogger(__name__)


@bp.route("/login")
def login():
    """Redirect to SSO login page with CSRF state."""
    state = secrets.token_urlsafe(32)
    session["sso_state"] = state

    base_url = current_app.config["OAUTH_BASE_URL"]
    callback = url_for("sso.callback", _external=True)

    return redirect(f"{base_url}/login?next={callback}&state={state}")


@bp.route("/callback")
def callback():
    """Handle SSO redirect — validate token, create session."""
    error = request.args.get("error")
    if error:
        logger.warning("SSO returned error: %s", error)
        abort(401, f"SSO login failed: {error}")

    # Verify CSRF state
    state = request.args.get("state", "")
    expected_state = session.pop("sso_state", None)
    if not expected_state or state != expected_state:
        logger.warning(
            "State mismatch: expected=%s got=%s session_keys=%s",
            expected_state, state, list(session.keys()),
        )
        abort(403, "CSRF state mismatch — session cookie may have been lost")

    token = request.args.get("token", "")
    if not token:
        abort(401, "No token received from SSO")

    # Validate token with SSO service endpoint
    base_url = current_app.config["OAUTH_BASE_URL"]
    client_id = current_app.config.get("SSO_CLIENT_ID", "")
    client_secret = current_app.config.get("SSO_CLIENT_SECRET", "")

    headers = {"Authorization": f"Bearer {token}"}
    if client_id and client_secret:
        endpoint = f"{base_url}/api/auth/me/service"
        headers["X-SSO-Client-Id"] = client_id
        headers["X-SSO-Client-Secret"] = client_secret
    else:
        endpoint = f"{base_url}/api/auth/me"

    try:
        resp = httpx.get(endpoint, headers=headers, timeout=10.0)
    except httpx.RequestError:
        logger.exception("SSO unreachable during callback")
        abort(502, "SSO service unreachable")

    if resp.status_code != 200:
        logger.warning("SSO token validation failed: %s", resp.status_code)
        abort(401, "Token validation failed")

    access_blob = resp.json()

    # Store in session
    session["sso_token"] = token
    session["sso_user"] = {
        "user_guid": access_blob.get("user_guid"),
        "email": access_blob.get("email"),
        "user_type": access_blob.get("user_type"),
        "is_su_admin": access_blob.get("is_su_admin", False),
        "display_name": access_blob.get("email", "User"),
    }

    logger.info("SSO login: %s", access_blob.get("email"))

    # Redirect to where they wanted to go, or admin dashboard
    next_url = session.pop("sso_next", None) or url_for("admin.dashboard")
    return redirect(next_url)


@bp.route("/logout")
def logout():
    """Log out — revoke token on SSO, clear local session."""
    token = session.get("sso_token")
    if token:
        base_url = current_app.config["OAUTH_BASE_URL"]
        try:
            httpx.post(
                f"{base_url}/api/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0,
            )
        except httpx.RequestError:
            pass

    session.clear()
    return redirect(url_for("sso.login"))
