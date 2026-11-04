#!/usr/bin/env python3
"""Mint a SCOPED, identity-less API key for a machine caller (#905).

Run it INSIDE the container, because that is the only place the real
database is:

    docker exec -i ips-app-1 python scripts/mint_service_key.py \
        --label alert.pdhc --scope implants:write

WHY THIS EXISTS RATHER THAN `POST /api/v1/auth/keys`.

The HTTP mint route sets `user_guid = g.current_user.guid`, so a key
minted over HTTP always carries the identity of whoever minted it. As
`auth_service` says in its own #903 note: *a key minted by an SU is an
SU key*, and the scope narrows the ROUTE, not the identity behind the
key. For a machine caller that is the wrong shape -- alert.pdhc should
be able to push implant assertions and nothing else, regardless of who
happened to be logged in the day it was set up.

`ApiKey.user_guid` is nullable, and `require_auth` already handles the
null case:

    if api_key.user: g.current_user = api_key.user
    else:            g.current_user = _service_account_user(api_key)

`_service_account_user` builds a TRANSIENT user with
`role="service_account"` and `is_superuser=False`, which is exactly what
a machine should get. This script is the only way to reach that state,
because the HTTP route cannot produce it.

THE SCOPE IS MANDATORY, AND THAT IS THE WHOLE POINT.

An identity-less key with `scopes=[]` is WORSE than an SU-backed one, not
better: it reaches every `@require_auth` route -- the FHIR surface,
patients, blocks, consents, state, export -- while looking narrow because
it has no user. That is the #760 shape (a read allowlist that granted
writes) arrived at from the opposite direction. So `--scope` is required,
and an unrecognised scope is refused by default: a typo mints a key that
cannot do its job, and the failure surfaces much later as a 403 that
looks like a credential problem.

THE PLAINTEXT IS SHOWN ONCE, TO THE OPERATOR, AND IS NEVER STORED.

Only `sha256(key)` goes to the database, and this script prints no key
material to any log. Copy it into the consumer's `.env` when it appears;
there is no way to recover it afterwards. Rotate by minting a new key and
revoking the old one -- never by reading this one back, which is
impossible by design.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import secrets
import sys

# Running a script puts ITS directory on sys.path, not the app root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", required=True,
                    help="who this key is for, e.g. 'alert.pdhc'")
    ap.add_argument("--scope", action="append", default=[], metavar="SCOPE",
                    help="repeatable; at least one is required")
    ap.add_argument("--force", action="store_true",
                    help="mint even though an active key with this label exists")
    ap.add_argument("--allow-unknown-scope", action="store_true",
                    help="permit a scope this build does not enforce")
    args = ap.parse_args(argv)

    # The pure guards run BEFORE the app imports, deliberately. A refusal
    # this cheap must not depend on a working app environment -- the first
    # draft imported first and so answered a missing --scope with a
    # ModuleNotFoundError instead of the refusal it had been given.
    scopes = sorted({s.strip() for s in args.scope if s.strip()})
    if not scopes:
        print("ABORT: --scope is required. An identity-less key with no scope "
              "reaches every @require_auth route in ips while looking narrow "
              "because it has no user. Mint it narrow or not at all.",
              file=sys.stderr)
        return 2

    from app import create_app
    from app.models.base import db
    from app.models.api_key import ApiKey
    from app.services import auth_service
    from app.services.audit_service import log_event

    # Every scope this build actually enforces. Collected from the module
    # rather than hand-listed, so a new SCOPE_* constant is recognised
    # without editing this script.
    known = {v for k, v in vars(auth_service).items()
             if k.startswith("SCOPE_") and isinstance(v, str)}
    unknown = [s for s in scopes if s not in known]
    if unknown and not args.allow_unknown_scope:
        print(f"ABORT: this build enforces no such scope: {unknown}. "
              f"Known: {sorted(known) or '(none)'}. A typo here mints a key "
              "that cannot do its job, and the failure arrives later as a 403 "
              "that reads like a credential problem. Use "
              "--allow-unknown-scope only if the route is not deployed yet.",
              file=sys.stderr)
        return 2

    app = create_app()
    with app.app_context():
        existing = (db.session.query(ApiKey)
                    .filter_by(label=args.label, is_active=True)
                    .all())
        live = [k for k in existing if not k.revoked_at]
        if live and not args.force:
            print(f"ABORT: {len(live)} active key(s) already carry the label "
                  f"{args.label!r}: "
                  + ", ".join(f"{k.prefix}… scopes={k.scopes}" for k in live)
                  + ". Minting another would leave two live credentials for "
                    "one consumer, and revoking the wrong one is an outage. "
                    "Revoke first, or pass --force deliberately.",
                  file=sys.stderr)
            return 3

        raw = secrets.token_urlsafe(48)
        key = ApiKey(
            user_guid=None,          # <- the point; see the module docstring
            key_hash=auth_service.hash_api_key(raw),
            label=args.label,
            prefix=raw[:8],
            scopes=scopes,
        )
        db.session.add(key)
        log_event("api_key_create", resource_guid=key.guid,
                  detail={"label": args.label, "scopes": scopes,
                          "identity": "none (service account)",
                          "minted_by": "scripts/mint_service_key.py"})
        db.session.commit()

        # Prove the key works through the REAL code path, not by trusting
        # that a row was inserted. Asserting on the row would only restate
        # the INSERT; these go through the functions the request path uses.
        checked = auth_service.validate_api_key(raw)
        if checked is None or str(checked.guid) != str(key.guid):
            db.session.rollback()
            print("ABORT: validate_api_key did not resolve the key just "
                  "minted. Rolled back.", file=sys.stderr)
            return 4
        if set(checked.scopes or []) != set(scopes):
            print(f"ABORT: stored scopes {checked.scopes!r} != {scopes!r}.",
                  file=sys.stderr)
            return 4
        if checked.user is not None:
            print("ABORT: the key resolved to a USER. It must be "
                  "identity-less.", file=sys.stderr)
            return 4
        sa = auth_service._service_account_user(checked)
        if sa.is_superuser or sa.role != "service_account":
            print(f"ABORT: service account is not narrow: role={sa.role!r} "
                  f"is_superuser={sa.is_superuser!r}.", file=sys.stderr)
            return 4
        # A control. Without a refusal the four checks above prove only
        # that something answers, not that it discriminates.
        if auth_service.validate_api_key(raw + "x") is not None:
            print("ABORT: a WRONG key also validated. The checks above mean "
                  "nothing.", file=sys.stderr)
            return 4

        digest = hashlib.sha256(raw.encode()).hexdigest()
        print(f"minted  guid={key.guid}")
        print(f"        label={args.label}  scopes={scopes}")
        print(f"        identity=none -> service_account, is_superuser=False")
        print(f"        verified through validate_api_key, with a refused "
              f"control")
        print(f"        len={len(raw)}  sha256={digest[:16]}…")
        print()
        print("=" * 64)
        print("  The key below is shown ONCE and is not recoverable.")
        print("  Put it in the consumer's .env now, then clear your scrollback.")
        print("=" * 64)
        print()
        print(f"  {raw}")
        print()
        print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
