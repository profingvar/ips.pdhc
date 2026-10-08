"""Sync the vårdgivare/vårdenhet hierarchy from sso into ips's clinics.

sso owns the care hierarchy; ips mirrors it so that a consumer asking ips about
a patient gets BOTH levels without a second call to sso. That mirroring is the
only honest arrangement: two authorities for one fact drift, and the drift is
invisible until someone compares them.

## The operator's rule, applied here

> "A guid must have a 1:1 relation to a personnummer, a caregiver and a
> careunit. If careunit is not given then the careunit should be set to the
> caregiver."

So when sso says an organisation has **no parent** — it IS a vårdgivare — this
writes `care_organisation_guid = organisation_guid`. The two levels are then
equal, which is exactly the fallback, and it is **stored** rather than left for
each reader to recompute. A rule that every consumer re-derives is a rule that
some consumer gets wrong.

## What it refuses to do

It never invents a caregiver. An organisation sso does not know is reported and
left alone, because guessing a parent would assert a legal relationship. ips
holding an organisation sso never issued is a real condition, not a
hypothetical — it was #767 and #780.
"""
import json
import urllib.error
import urllib.request

from flask import current_app

from app.models.base import db
from app.models.clinic import Clinic


class SsoHierarchyUnavailable(RuntimeError):
    """sso could not be asked. Raised so a sync never half-applies."""


def _sso_get(path, token):
    base = (current_app.config.get("SSO_BASE_URL")
            or current_app.config.get("SSO_INTERNAL_URL") or "").rstrip("/")
    if not base:
        raise SsoHierarchyUnavailable("SSO_BASE_URL is not configured")
    if not token:
        raise SsoHierarchyUnavailable(
            "no sso token supplied — sso's require_auth accepts ONLY "
            "`Authorization: Bearer`, so this is a missing credential here, "
            "not an sso outage")
    # stdlib, not `requests`. ips has NO outbound HTTP dependency — nothing
    # else in the service makes an outgoing call and `requests` is not in
    # requirements.txt. Adding a pinned third-party dependency to the
    # platform's patient registry for one admin command is the wrong trade,
    # especially right after #785 pinned every version: a rebuild is also a
    # dependency upgrade.
    req = urllib.request.Request(base + path, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                raise SsoHierarchyUnavailable(
                    f"sso returned {r.status} for {path}")
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SsoHierarchyUnavailable(
            f"sso returned {e.code} for {path}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SsoHierarchyUnavailable(f"sso unreachable: {e}") from e
    return data if isinstance(data, list) else []


def sync(token, dry_run=True):
    """Fill `clinics.care_organisation_guid` from sso.

    Dry run by default. Returns a report; nothing is written unless
    `dry_run=False`.
    """
    units = _sso_get("/api/registry/care-units", token)
    orgs = _sso_get("/api/registry/care-organisations", token)

    parent_of = {str(u.get("care_unit_guid")): str(u.get("care_organisation_guid") or "")
                 for u in units}
    caregiver_guids = {str(o.get("care_organisation_guid")) for o in orgs}

    actions, unknown, unchanged = [], [], 0
    for c in db.session.query(Clinic).all():
        org = str(c.organisation_guid or "")
        if not org:
            unknown.append({"clinic": c.name, "why": "clinic has no organisation_guid"})
            continue
        if org in parent_of and parent_of[org]:
            want, why = parent_of[org], "sso: vårdenhet under this vårdgivare"
        elif org in caregiver_guids or org in parent_of:
            # Either sso lists it as a vårdgivare, or as a unit with no
            # parent. Both mean it is its own caregiver — the operator's
            # fallback, written explicitly.
            want, why = org, "sso: no parent, so careunit := caregiver"
        else:
            unknown.append({"clinic": c.name, "org_guid": org,
                            "why": "sso does not know this organisation — NOT "
                                   "guessing a caregiver for it"})
            continue
        if str(c.care_organisation_guid or "") == want:
            unchanged += 1
            continue
        actions.append({"clinic": c.name, "org_guid": org,
                        "from": c.care_organisation_guid, "to": want,
                        "why": why})
        if not dry_run:
            c.care_organisation_guid = want

    if not dry_run:
        db.session.commit()

    return {"dry_run": dry_run, "clinics": db.session.query(Clinic).count(),
            "would_change" if dry_run else "changed": actions,
            "already_correct": unchanged, "unresolved": unknown}


def format_report(r):
    mode = "DRY RUN — nothing written" if r["dry_run"] else "APPLIED"
    key = "would_change" if r["dry_run"] else "changed"
    out = ["care-hierarchy sync — %s" % mode,
           "  clinics examined   : %d" % r["clinics"],
           "  already correct    : %d" % r["already_correct"],
           "  %-18s : %d" % (key, len(r[key]))]
    for a in r[key]:
        out.append("      %-24s %s -> %s   (%s)"
                   % (a["clinic"], (a["from"] or "NULL")[:8], a["to"][:8],
                      a["why"]))
    if r["unresolved"]:
        out.append("  UNRESOLVED         : %d  (left alone — a guessed parent "
                   "would assert a legal relationship)" % len(r["unresolved"]))
        for u in r["unresolved"]:
            out.append("      %-24s %s" % (u.get("clinic"), u["why"]))
    if r["dry_run"]:
        out.append("  Re-run with --no-dry-run to apply.")
    return "\n".join(out)
