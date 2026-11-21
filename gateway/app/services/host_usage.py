"""Count API requests per (Host, caller) -- the phase-4 evidence (#1017).

Epic #1015 retires ``ips.pdhc.se`` only after it has carried zero traffic
for seven days, per caller. So every API request (``/api/``, ``/fhir/``,
``/external/``) increments one row of ``host_usage``, keyed by the Host
header it arrived with and WHO sent it.

Why a table and not a log line: the question is asked a week or more after
the fact, per caller, and container logs are rotated and recreated with the
container (CLAUDE.md §7). A row per (host, caller) is small -- the number of
distinct callers, not the number of requests -- and is answered by
``flask host-usage``.

The identity is never a secret (see ``caller_identity``). Recording can
never break a request: it runs after the response is built, on its own
connection, and any failure is logged once per process and swallowed.
"""
from __future__ import annotations

import logging
import re

from flask import current_app, g, request
from sqlalchemy import DateTime, bindparam, text

from app.models.base import db, utcnow

logger = logging.getLogger(__name__)

COUNTED_PREFIXES = ("/api/", "/fhir/", "/external/")

_UA_PRODUCT = re.compile(r"[A-Za-z0-9._-]{1,40}")

_UPSERT = text(
    "INSERT INTO host_usage "
    "(host, caller_kind, caller_id, caller_label, count, first_seen, last_seen) "
    "VALUES (:host, :kind, :cid, :label, 1, :now, :now) "
    "ON CONFLICT (host, caller_kind, caller_id) DO UPDATE SET "
    "count = host_usage.count + 1, last_seen = :now, "
    "caller_label = COALESCE(:label, host_usage.caller_label)"
).bindparams(bindparam("now", type_=DateTime(timezone=True)))

_warned = False


def is_counted(path: str) -> bool:
    return path.startswith(COUNTED_PREFIXES) or path == "/fhir"


def counted_host() -> str:
    """The Host the caller used, lowercased, port kept (an internal caller
    on ``host.docker.internal:9040`` is a different caller from the public
    name, and phase 4 wants to see both)."""
    return (request.host or "").strip().lower()[:255] or "-"


def caller_identity() -> tuple[str, str, str | None]:
    """(kind, id, label) for the current request. Never a credential.

    apikey      -- ``g.api_key``: its row guid, label = the key's label
    read_grant  -- ``g.read_grant``: the partner guid, label = partner name
    bearer      -- ``g.access_blob``: the SSO ``user_type`` (a TYPE, not a user)
    dev         -- AUTH_DISABLED (local/test only)
    rejected    -- a credential was sent and refused: id = its scheme only
    anonymous   -- no credential: id = the User-Agent's product token
    """
    key = g.get("api_key")
    if key is not None:
        return "apikey", str(getattr(key, "guid", "") or "?"), \
            (getattr(key, "label", None) or None)
    grant = g.get("read_grant")
    if isinstance(grant, dict):
        return "read_grant", str(grant.get("partner_guid") or "?"), \
            (grant.get("partner_name") or None)
    blob = g.get("access_blob")
    if isinstance(blob, dict) and blob:
        return "bearer", str(blob.get("user_type") or "unknown")[:128], None
    if current_app.config.get("AUTH_DISABLED"):
        return "dev", "auth_disabled", None
    auth = request.headers.get("Authorization", "")
    if auth:
        scheme = auth.split(" ", 1)[0][:32] or "?"
        return "rejected", scheme, None
    m = _UA_PRODUCT.match(request.headers.get("User-Agent", "") or "")
    return "anonymous", (m.group(0) if m else "-"), None


def record_request(response):
    """``after_request`` hook. Returns the response unchanged."""
    global _warned
    try:
        if request.method == "OPTIONS" or not is_counted(request.path):
            return response
        kind, cid, label = caller_identity()
        params = {"host": counted_host(), "kind": kind, "cid": cid[:128],
                  "label": (label or None) and label[:255], "now": utcnow()}
        with db.engine.begin() as conn:
            conn.execute(_UPSERT, params)
    except Exception:  # noqa: BLE001 -- a counter must never break a request
        if not _warned:
            _warned = True
            logger.warning("eps.pdhc host_usage: could not record a request",
                           exc_info=True)
    return response


def rows(host: str | None = None):
    from app.models.host_usage import HostUsage
    q = db.session.query(HostUsage)
    if host:
        q = q.filter(HostUsage.host == host.lower())
    return q.order_by(HostUsage.host, HostUsage.last_seen.desc()).all()
