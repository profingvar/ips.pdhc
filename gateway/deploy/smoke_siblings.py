#!/usr/bin/env python3
"""ips.pdhc — does every call to a SIBLING service actually work? (#708)

Run it INSIDE the container, because that is the only place the real
credentials and the real network names exist:

    docker exec ips-app-1 python deploy/smoke_siblings.py
    docker exec ips-app-1 python deploy/smoke_siblings.py --json

READ-ONLY. It creates nothing, writes nothing, and mints no token, so it is
safe against production at any time, including immediately after a deploy.

## Why ips needs one even though it only calls sso

ips is the service everything else asks about consent and spärr, so it looks
like a leaf. It is not: every authenticated request it serves is validated by
calling sso, and the care-hierarchy sync reads sso's registry. If either path
drifts, ips does not break loudly — it refuses every caller, which looks
exactly like a credential problem at the CALLER. #708 was filed because that
class of defect is invisible to unit tests inside one repo.

## The 401-vs-404 probe, and why it is the whole point

`resolve_sso_user` swallows every failure and returns None, by design: a token
that cannot be resolved is not a user. That means None is returned for a
REJECTED token and for an UNREACHABLE sso alike, so calling the client and
getting None proves nothing at all.

So each sso path is probed twice:

  * directly, with a deliberately invalid credential, asserting **401 and not
    404**. A 404 means the path moved and ips would refuse every caller;
  * through ips's own client, asserting it reaches the service rather than
    erroring on the way out.

This is the read-only half of a write edge: it exercises the contract without
holding a real token.
"""
from __future__ import annotations

import json as _json
import pathlib
import re
import sys
import time

# Running a script puts ITS directory on sys.path, not the app root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

#: Every sso path ips depends on -> the client module that builds it.
#: Templates, not bare strings, and checked anchored (see
#: `_path_appears_in_client`), because `auth/me` is a substring of
#: `auth/me/service` and a truncated prefix must not pass — the #804 lesson.
PROBED_PATHS = {
    "/api/auth/me/service": "services/auth_service.py",
    "/api/registry/care-units": "services/care_hierarchy_sync.py",
    "/api/registry/care-organisations": "services/care_hierarchy_sync.py",
}

#: Probed but composed inline here, with no client module to drift from:
#:   /api/health   sso liveness
INLINE_PATHS = ("/api/health",)

RESET, RED, GRN, BOLD = "\033[0m", "\033[31m", "\033[32m", "\033[1m"

results: list[dict] = []


def check(name: str):
    def wrap(fn):
        started = time.time()
        try:
            ok, note = fn()
        except Exception as e:                      # noqa: BLE001
            ok, note = False, f"{type(e).__name__}: {e}"
        results.append({"check": name, "ok": bool(ok), "note": note,
                        "ms": int((time.time() - started) * 1000)})
        return ok
    return wrap


def _client_root() -> pathlib.Path:
    """Where the client modules live, in the image AND in a checkout.

    The image is /app/app/... while a checkout is <repo>/gateway/app/..., so
    one hardcoded relative path resolves in only one of them — gateway's guard
    had exactly this problem and so could not be run before a deploy, which is
    when it would have been worth running (#804).
    """
    here = pathlib.Path(__file__).resolve().parent.parent
    for cand in (here / "app", here / "gateway" / "app"):
        if cand.is_dir():
            return cand
    return here / "app"


def _path_appears_in_client(template: str, src: str) -> bool:
    """ANCHORED on the first literal fragment: a bare `in` check accepts a
    truncated prefix, which is the bug this guard exists for."""
    frags = [f for f in template.split("%s") if f]
    if not frags:
        return False
    if not re.search(r"""[}"']""" + re.escape(frags[0]), src):
        return False
    return all(f in src for f in frags[1:])


def _get(url, headers=None, timeout=10):
    """stdlib only. ips has NO outbound HTTP dependency — `requests` is not in
    its requirements.txt and `care_hierarchy_sync` says why. A smoke that
    imported one would be testing a stack the service does not have."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2048)
    except urllib.error.HTTPError as e:
        return e.code, e.read(2048)


def main(as_json: bool = False) -> int:
    from app import create_app
    app = create_app()

    with app.app_context():
        from flask import current_app
        cfg = current_app.config
        sso = (cfg.get("OAUTH_BASE_URL") or "").rstrip("/")
        registry = (cfg.get("SSO_BASE_URL") or cfg.get("SSO_INTERNAL_URL")
                    or sso or "").rstrip("/")

        @check("paths: every probed path appears in its client module")
        def _():
            root = _client_root()
            missing = []
            for template, mod in PROBED_PATHS.items():
                f = root / mod
                if not f.exists():
                    missing.append(f"{mod} is missing (looked in {root})")
                    continue
                if not _path_appears_in_client(template,
                                               f.read_text(encoding="utf-8")):
                    missing.append(f"{template} does not START a URL in {mod}")
            return (not missing), (
                f"all {len(PROBED_PATHS)} anchored to a URL boundary; "
                f"{len(INLINE_PATHS)} inline liveness path(s) unguarded by "
                f"design" if not missing else "; ".join(missing))

        @check("config: OAUTH_BASE_URL is set")
        def _():
            return bool(sso), sso or "MISSING"

        @check("config: the care-hierarchy sync can resolve an sso base url")
        def _():
            # A separate check from the one above, because they used to be
            # different answers: ips sets OAUTH_BASE_URL and this module read
            # only SSO_BASE_URL / SSO_INTERNAL_URL, so the sync refused with
            # "SSO_BASE_URL is not configured" before reaching the token.
            # This check is what found it (#708).
            from app.services.care_hierarchy_sync import _SSO_URL_KEYS, _sso_base
            base = _sso_base()
            if not base:
                return False, ("none of " + ", ".join(_SSO_URL_KEYS)
                               + " is set — sync-care-hierarchy cannot run")
            which = next(k for k in _SSO_URL_KEYS if (cfg.get(k) or "").strip())
            return True, f"{base} (from {which})"

        @check("config: the sso service credential pair is configured")
        def _():
            # Without BOTH, `resolve_sso_user` silently falls back to
            # /api/auth/me, which is the USER endpoint. ips would then be
            # validating tokens through a path never intended for a service,
            # and the only symptom is 401s that look like the caller's fault
            # (memory: PDHC SSO client creds audit).
            cid, sec = cfg.get("SSO_CLIENT_ID"), cfg.get("SSO_CLIENT_SECRET")
            if cid and sec:
                return True, "client id + secret present"
            return False, ("MISSING — resolve_sso_user would fall back to the "
                           "USER endpoint /api/auth/me")

        @check("sso: /api/health answers 200")
        def _():
            if not sso:
                return False, "OAUTH_BASE_URL not set"
            code, _body = _get(f"{sso}/api/health")
            return code == 200, f"{code}"

        @check("sso: /api/auth/me/service EXISTS (401 for a junk token, not 404)")
        def _():
            # The probe that matters. `resolve_sso_user` returns None for a
            # rejected token AND for an unreachable sso, so a 404 here would
            # make ips refuse every caller with no error anywhere.
            if not sso:
                return False, "OAUTH_BASE_URL not set"
            code, _body = _get(f"{sso}/api/auth/me/service", headers={
                "Authorization": "Bearer smoke-not-a-real-token",
                "X-SSO-Client-Id": cfg.get("SSO_CLIENT_ID") or "",
                "X-SSO-Client-Secret": cfg.get("SSO_CLIENT_SECRET") or "",
                "Accept": "application/json"})
            if code == 404:
                return False, ("404 — the path MOVED. ips would refuse every "
                               "authenticated caller and blame the caller")
            if code == 200:
                return False, "200 for a junk token — sso accepted nonsense"
            return code in (401, 403), f"{code} (rejected, so the path is live)"

        @check("sso: ips's own client reaches that endpoint")
        def _():
            # Drives `resolve_sso_user`, so a wrong header, a wrong scheme or
            # a broken httpx call is wrong here too. None is the only correct
            # answer for a junk token; the value of this check is that the
            # call completes at all, which the probe above makes meaningful.
            from app.services.auth_service import resolve_sso_user
            got = resolve_sso_user("smoke-not-a-real-token")
            return got is None, ("None, as it must be for an invalid token"
                                 if got is None else f"RESOLVED a junk token: "
                                 f"{str(got)[:80]}")

        for path in ("/api/registry/care-units",
                     "/api/registry/care-organisations"):
            @check(f"sso: {path} EXISTS (401 for no credential, not 404)")
            def _(path=path):
                if not registry:
                    return False, "no sso base url configured"
                code, _body = _get(f"{registry}{path}",
                                   headers={"Accept": "application/json"})
                if code == 404:
                    return False, ("404 — the path MOVED; `flask sync-care-"
                                   "hierarchy` would report an sso outage")
                if code == 200:
                    return False, ("200 with NO credential — sso's care "
                                   "registry is unauthenticated")
                return code in (401, 403), f"{code}"

        @check("sync: a missing sso token refuses by NAME, not as an outage")
        def _():
            # The distinction is the whole value of the error: "no token" is a
            # missing credential HERE, while "unreachable" is sso's problem,
            # and conflating them sends the operator to the wrong service.
            from app.services.care_hierarchy_sync import (
                SsoHierarchyUnavailable, sync)
            try:
                sync(token=None, dry_run=True)
            except SsoHierarchyUnavailable as e:
                msg = str(e)
                if "token" not in msg.lower():
                    return False, (f"refused for the wrong reason: {msg[:90]}"
                                   " — the operator would be sent to the "
                                   "wrong service")
                return True, msg[:110]
            return False, "it proceeded with no token"

    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(_json.dumps({"service": "ips.pdhc", "checks": results,
                           "failed": len(failed)}, indent=2))
    else:
        print(f"\n{BOLD}ips.pdhc — sibling smoke{RESET}\n")
        for r in results:
            mark = f"{GRN}OK{RESET}" if r["ok"] else f"{RED}FAIL{RESET}"
            print(f"  {mark:<14} {r['check']:<62} {r['note']}  ({r['ms']}ms)")
        if failed:
            print(f"\n{RED}{BOLD}{len(failed)} check(s) failed.{RESET} ips "
                  f"cannot authenticate anyone until these pass.\n")
        else:
            print(f"\n{GRN}{BOLD}All {len(results)} checks passed.{RESET}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(as_json="--json" in sys.argv))
