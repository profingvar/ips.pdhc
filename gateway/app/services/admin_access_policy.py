"""Who may use ips's HTML admin surface — #902.

ONE PLACE, as #902 asks, rather than a rule repeated per route. All 23
admin routes are gated by a single ``before_request``; this module is the
decision it consults.

== What was measured, 2026-11-02 ==

#902 was filed with its uncertainty stated: whether the session-only gate
was EXPOSURE depended on something outside ips — whether sso.pdhc would
issue a usable token for ips to an arbitrary user, or only to users with
the right affiliation. That is now measured, in code on both sides, and
the answer is that sso does NOT gate it:

  - ``sso.pdhc/app/src/routes/auth.py:123`` — ``/api/auth/me/service``
    authenticates the USER (``@require_auth``) and authenticates the
    SERVICE (constant-time client-id/secret compare), and then builds the
    blob with **no check whatsoever** that this user may use this service.
  - sso has no per-user service allowlist. ``allowed_services`` exists
    only on ``Organisation``, for the machine/partner path
    (``routes/partners.py``), never for a human user's token.
  - ``ips.pdhc/gateway/app/api/sso_routes.py`` stores the returned blob in
    the session on any 200. It even reads ``user_type`` and
    ``is_su_admin`` into ``session['sso_user']`` — and the gate then
    consulted neither.

So any authenticated platform user who completed ips's SSO callback —
**a patient included** — obtained the whole admin surface. That is 23
routes, of which TEN are writes: create patient, archive, unarchive,
add-resource, create-card, create-snapshot, push-snapshot,
create-destination, mock-data and ``mock-data/purge``, which deletes
patients, clinical resources and clinic assignments.

== The deliberate split, and why ==

CLAUDE.md §11 states that ips belongs to the analysis phase and that
access requires ``is_su_admin`` OR (``user_type == 'professional'`` AND
``'analysis' in effective_phases``). ips implements none of that — not
here and not in ``require_auth`` either, which has zero references to
``effective_phases``. So the handbook is wrong about ips on BOTH
surfaces.

Implementing the whole rule at once carries a real risk the measurement
cannot remove: **it could lock legitimate users out of their own tool.**
Who logs into ips admin today is not knowable from this repo. So the rule
ships in two halves:

  1. **Unconditional, now.** A caller who is not a professional and not an
     SU admin is REFUSED. This cannot lock out any legitimate
     administrator, because no legitimate administrator of a patient
     registry is a patient.

  2. **Shadow-logged, behind a flag.** The ``'analysis'`` phase
     requirement is evaluated on every request and the refusals it WOULD
     have made are logged, but not enforced until
     ``IPS_ADMIN_REQUIRE_ANALYSIS_PHASE`` is set. That gives the operator
     the one thing needed to decide — evidence of who would be affected —
     without a lockout. Same shape as the platform's own
     ``SSO_EMIT_LEGACY_BLOB_FIELDS`` soak.

Flip the flag when the shadow log is quiet.

== The download exemption was a substring match ==

The gate used to read ``if "download" in request.endpoint: return None``,
which exempted four doc-download endpoints — and would silently exempt
ANY future endpoint whose name happened to contain "download". That is
the #804 shape: a check that matches a name rather than naming a
capability. It is now an explicit set, so adding an endpoint cannot
quietly open it.
"""

import logging

logger = logging.getLogger(__name__)

# Endpoints deliberately reachable without a session: the four rendered
# documentation downloads, which contain no patient data. An explicit
# set, never a substring test.
PUBLIC_ADMIN_ENDPOINTS = frozenset({
    "admin.docs_api_download",
    "admin.docs_capability_download",
    "admin.docs_manual_download",
    "admin.docs_technical_download",
})

# The phase CLAUDE.md §11 says ips belongs to.
ADMIN_REQUIRED_PHASE = "analysis"

def _phases(blob):
    """Reform-canonical phases: prefer ``session_phases``, fall back to
    the dual-emitted legacy ``effective_phases``.

    NOT a stylistic choice, and getting it wrong is a dated bug. All
    three sibling services in CLAUDE.md §11's list do exactly this —
    `dashboard.pdhc/app/auth.py:66` (#415),
    `rosetta.pdhc/app/auth.py:38` (#417),
    `cdr.pdhc/cdr_app/app/auth.py:42` (#416) — and
    ``effective_phases`` is on sso's ``LEGACY_BLOB_FIELDS`` kill-switch
    list (`sso.pdhc/app/src/services/auth_service.py:46-49`), staged to
    stop being emitted when ``SSO_EMIT_LEGACY_BLOB_FIELDS`` is flipped
    to false (#409).

    So a gate reading only the legacy field would see an EMPTY phase
    list the day that flag flips, and would then shadow-deny — or, once
    this module's own flag is set, refuse — every professional on the
    platform. Reading the canonical field first makes this gate
    independent of #409's timing.
    """
    if not isinstance(blob, dict):
        return []
    return blob.get("session_phases") or blob.get("effective_phases") or []


REASON_NO_SESSION = "no_session"
REASON_NOT_PROFESSIONAL = "not_professional"
REASON_PHASE_MISSING = "analysis_phase_missing"

# Config key that promotes the phase rule from shadow-logged to enforced.
PHASE_FLAG = "IPS_ADMIN_REQUIRE_ANALYSIS_PHASE"


def admin_access_decision(sso_user, *, enforce_phase=False):
    """Decide one request against ips's admin surface.

    Args:
        sso_user: the ``session['sso_user']`` dict, or None.
        enforce_phase: when True the analysis-phase requirement is
            binding; when False it is evaluated and reported but does not
            deny.

    Returns:
        ``(allowed, reason, shadow_reason)``.

        ``reason`` is the code for an actual denial, None when allowed.
        ``shadow_reason`` is the code this request WOULD have been denied
        for had ``enforce_phase`` been True — None when it would have
        passed either way. It is never set when ``reason`` is set, so the
        shadow log counts only the users the flag would newly affect.

    Missing or malformed input denies. An admin surface is the wrong
    place to be generous about a value one cannot read.
    """
    if not isinstance(sso_user, dict) or not sso_user:
        return False, REASON_NO_SESSION, None

    is_su = bool(sso_user.get("is_su_admin"))
    user_type = sso_user.get("user_type")

    # --- half 1: unconditional. An SU passes; otherwise a professional
    # is required. A patient, a relative (#890) or an unrecognised type
    # is refused outright.
    if not is_su and user_type != "professional":
        return False, REASON_NOT_PROFESSIONAL, None

    # --- half 2: the analysis phase. An SU is exempt, per §11's own
    # "is_su_admin OR (...)".
    if is_su:
        return True, None, None

    phases = _phases(sso_user)
    has_phase = ADMIN_REQUIRED_PHASE in phases
    if has_phase:
        return True, None, None

    if enforce_phase:
        return False, REASON_PHASE_MISSING, None

    # Shadow: allowed today, would be refused once the flag is set.
    return True, None, REASON_PHASE_MISSING


def log_shadow_denial(sso_user, endpoint, shadow_reason):
    """Record a request the phase rule would have refused.

    Deliberately a WARNING and deliberately naming the user: the whole
    purpose is to give the operator a list of who would be affected
    before the flag is flipped. A silent counter would not answer the
    question the flag exists to answer.
    """
    logger.warning(
        "ips admin shadow-denial (%s): endpoint=%s user_guid=%s "
        "user_type=%s phases=%s — this request WOULD be refused once %s "
        "is set",
        shadow_reason, endpoint,
        (sso_user or {}).get("user_guid"),
        (sso_user or {}).get("user_type"),
        _phases(sso_user),
        PHASE_FLAG,
    )
