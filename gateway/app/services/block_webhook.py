"""Outbound block-state webhooks — IPS Renov 6 (#202).

Signs each notification with HMAC-SHA256 (header form
``X-PDHC-Signature: sha256=<hex>``) — same convention as
``request.pdhc/gateway/app/services/webhook_dispatcher`` so consumer
implementations don't need a second verifier.

What this is and isn't:
  - This is a *cache-invalidation hint*. The body carries enough to let
    a subscriber drop the right cache entry (patient_guid +
    source_scope_id + event_type); it does not carry PHI.
  - Failures are best-effort: a target that doesn't respond gets a
    WARNING log and no retry from this side. Subscribers fall back to
    the existing 30 s cache TTL when a webhook is missed (the design
    point legal confirmed 2026-06-04 was that TTL alone is acceptable
    — the webhook is the cherry on top, not the load-bearing
    primitive).
  - There is no per-subscriber signing key. IPS holds one secret and
    every subscriber configures the same one. Provider-style per-org
    secrets (request.pdhc #136) are not used here because the
    subscriber set is the small fixed set of PDHC services, not a
    long-tail of external providers.

Event types emitted:
  block.created       — new PatientBlock row, ``is_active=True``
  block.lifted        — operator/patient lifted (consent or
                        indispensable_care)
  block.expired       — sweep detected ``expires_at < now`` and flipped
                        ``lifted_at`` (#202)
  block.re_imposed    — sweep detected an indispensable_care lift past
                        ``lift_expires_at`` (#202)

Body shape (sorted keys, canonical JSON):
  {
    "event_type":         "block.<...>",
    "block_guid":         "<uuid>",
    "patient_guid":       "<uuid>",
    "source_scope_type":  "clinic" | "caregiver",
    "source_scope_id":    "<uuid>",
    "is_active":          true | false,
    "occurred_at":        "<iso-8601-utc>"
  }
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from flask import current_app


log = logging.getLogger(__name__)


_VALID_EVENTS = (
    "block.created", "block.lifted",
    "block.expired", "block.re_imposed",
)


def compute_signature(secret: str, body_bytes: bytes) -> str:
    """HMAC-SHA256 hex digest. Header form: 'sha256=<hex>'."""
    digest = hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _build_body(event_type: str, block) -> bytes:
    """Canonical JSON body. Stable ordering so the signature is
    reproducible (subscribers re-sign and compare)."""
    occurred_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_type": event_type,
        "block_guid": str(block.guid),
        "patient_guid": str(block.patient_guid),
        "source_scope_type": block.source_scope_type,
        "source_scope_id": str(block.source_scope_id),
        "is_active": bool(block.is_active()),
        "occurred_at": occurred_at,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def dispatch_block_event(event_type: str, block) -> dict:
    """Sign + deliver one notification to every configured target.

    Returns a small summary suitable for tests + logs:
      {"delivered": N, "failed": N, "skipped": str | None,
       "signature": "sha256=<hex>" | None,
       "body": <bytes that were signed>}
    """
    if event_type not in _VALID_EVENTS:
        raise ValueError(
            f"unknown block event_type: {event_type!r}",
        )

    secret = current_app.config.get("IPS_WEBHOOK_SECRET") or ""
    targets = current_app.config.get("IPS_WEBHOOK_TARGETS") or []
    timeout = float(
        current_app.config.get("IPS_WEBHOOK_TIMEOUT", 5),
    )

    body = _build_body(event_type, block)
    summary = {
        "delivered": 0, "failed": 0, "skipped": None,
        "signature": None, "body": body,
    }

    if not secret:
        log.warning(
            "block_webhook %s skipped: IPS_WEBHOOK_SECRET not set",
            event_type,
        )
        summary["skipped"] = "no_secret"
        return summary
    if not targets:
        # Silent skip — common in dev / standalone install.
        summary["skipped"] = "no_targets"
        return summary

    signature = compute_signature(secret, body)
    summary["signature"] = signature
    headers = {
        "Content-Type": "application/json",
        "X-PDHC-Signature": signature,
        "X-PDHC-Event": event_type,
    }
    for url in targets:
        try:
            r = httpx.post(
                url, content=body, headers=headers, timeout=timeout,
            )
        except httpx.HTTPError as e:
            log.warning(
                "block_webhook %s -> %s failed: %s",
                event_type, url, e,
            )
            summary["failed"] += 1
            continue
        if r.status_code >= 400:
            log.warning(
                "block_webhook %s -> %s HTTP %s",
                event_type, url, r.status_code,
            )
            summary["failed"] += 1
        else:
            summary["delivered"] += 1
    return summary


def safe_dispatch(event_type: str, block) -> None:
    """Wrapper used by state-changing routes: never raises.

    A failing webhook must not roll back the state transition that
    triggered it. The audit row IS the source of truth; the webhook
    is an optimisation."""
    try:
        dispatch_block_event(event_type, block)
    except Exception:  # noqa: BLE001
        log.warning(
            "block_webhook dispatch raised for %s on block %s",
            event_type, getattr(block, "guid", "?"),
            exc_info=True,
        )
