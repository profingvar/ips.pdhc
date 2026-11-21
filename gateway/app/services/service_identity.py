"""Who this service is, and which SSO client pair it speaks as (#1017).

The service is called ``eps.pdhc`` from #1017 on and answers on two
addresses during the rename (epic #1015): ``https://eps.pdhc.se`` and the old
``https://ips.pdhc.se``. Container, compose project, volume and database keep
their ``ips`` names on purpose (the data layer does not move).

sso.pdhc registers one client pair per callback host. So the pair ips uses
toward sso is chosen by the host the REQUEST arrived on:

    eps.pdhc.se   -> SSO_CLIENT_ID_EPS / SSO_CLIENT_SECRET_EPS,
                     falling back to SSO_CLIENT_ID / SSO_CLIENT_SECRET while
                     the EPS pair is not yet configured (so this deploys
                     before the operator registers it);
    anything else -> SSO_CLIENT_ID / SSO_CLIENT_SECRET, exactly as before.

The EPS pair is used only when BOTH halves are set; half a pair is a
misconfiguration, logged by name (never value), and the old pair is used.
"""
from __future__ import annotations

import logging

from flask import current_app, has_request_context, request

SERVICE_NAME = "eps.pdhc"
# What /api/v1/health said before #1017. Kept as an alias in the health body
# so anything that matched on it can still find it.
LEGACY_SERVICE_NAMES = ("ips-server", "ips.pdhc")

EPS_HOST = "eps.pdhc.se"

logger = logging.getLogger(__name__)


def request_hostname() -> str:
    """The host the request arrived on, lowercased, without port.

    ``request.host`` already honours X-Forwarded-Host via ProxyFix(x_host=1);
    nginx sends ``Host $host``. Empty outside a request.
    """
    if not has_request_context():
        return ""
    return (request.host or "").split(":", 1)[0].strip().lower()


def sso_client_pair() -> tuple[str, str]:
    """(client_id, client_secret) for the host this request came in on."""
    cfg = current_app.config
    old = (cfg.get("SSO_CLIENT_ID") or "", cfg.get("SSO_CLIENT_SECRET") or "")
    if request_hostname() != EPS_HOST:
        return old
    eid = cfg.get("SSO_CLIENT_ID_EPS") or ""
    esec = cfg.get("SSO_CLIENT_SECRET_EPS") or ""
    if eid and esec:
        return eid, esec
    if eid or esec:
        logger.warning(
            "eps.pdhc: only one of SSO_CLIENT_ID_EPS / SSO_CLIENT_SECRET_EPS "
            "is set; using SSO_CLIENT_ID / SSO_CLIENT_SECRET")
    return old
