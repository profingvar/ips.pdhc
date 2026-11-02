"""Canonical care-phase zone policy (access-model reform D3 #406).

ips owns the spärr rows (PatientBlock #197) and the cohesive-care
consents (PatientConsent #198), so ips owns the COMPOSED rule too — the
same single-source-of-truth principle as ``consent_policy.py`` (#422):
no two consumers may enforce different zone rules.

The v3 zone model (spec §4, decisions locked 2026-07-03):

  Zone 1 — same care unit (vårdrelation). The authoring unit always
           sees its own data; spärr never hides a unit's data from
           itself. access_basis = same_unit.
  Zone 2 — same care organisation, different unit (inre sekretess).
           Blocked by an active INRE spärr — a clinic-scoped
           PatientBlock on the authoring unit. Otherwise allowed,
           access_basis = same_org.
  Zone 3 — different care organisation (Lag 2022:913 §5 sammanhållen
           vård). Requires BOTH the patient's cohesive-care consent for
           the READING caregiver (an active PatientConsent row —
           "allow_sharing_in_care") AND the absence of spärr on the
           authoring side: no YTTRE spärr (caregiver-scoped block on
           the authoring caregiver) and no inre spärr on the authoring
           unit (a clinic block hides that unit's data from everyone
           outside the unit, across org boundaries included).
           access_basis = cross_org_consent.

  Nödöppning (PDL 6 kap 5 §) — an active EmergencyAccess grant for
  (patient, reading unit) overrides spärr AND absent consent in zones
  2–3. access_basis = emergency. The grant itself is attested,
  time-bound, audited, and patient-notified (care_access_routes).

Block lift mechanics are NOT re-implemented here: ``PatientBlock
.is_active()`` already folds in consent lifts and the auto-re-imposing
indispensable-care lift, so this module only consults active blocks.
The indispensable lift's concept-level mechanical filter
(lift_concept_guids) remains a consumer-side row filter exactly as
today — a lifted block simply isn't active here.

Missing/unknown inputs default to the SAFE value: no consent, blocks
present if given, unknown org relationships fall to Zone 3.
"""

# access_basis values from the closed enum in plans/pdhc_data_shapes.md §5.
BASIS_SAME_UNIT = "same_unit"
BASIS_SAME_ORG = "same_org"
BASIS_CROSS_ORG_CONSENT = "cross_org_consent"
BASIS_EMERGENCY = "emergency"

# Exclusion reason codes (stable API surface).
REASON_INRE_SPARR = "inre_sparr"
REASON_YTTRE_SPARR = "yttre_sparr"
REASON_NO_SHARING_CONSENT = "no_sharing_consent"


def zone_for(reader_care_unit_guid, reader_care_organisation_guid,
             author_clinic_guid, author_caregiver_guid) -> int:
    """Classify the read into zone 1, 2 or 3. Unknown relations → 3."""
    if reader_care_unit_guid and author_clinic_guid \
            and str(reader_care_unit_guid) == str(author_clinic_guid):
        return 1
    if reader_care_organisation_guid and author_caregiver_guid \
            and str(reader_care_organisation_guid) == str(author_caregiver_guid):
        return 2
    return 3


def _active_block_on(active_blocks, scope_type, scope_id):
    if not scope_id:
        return False
    sid = str(scope_id)
    for b in active_blocks or []:
        if b.source_scope_type == scope_type and str(b.source_scope_id) == sid:
            return True
    return False


def evaluate_care_access(
    *,
    reader_care_unit_guid,
    reader_care_organisation_guid,
    author_clinic_guid,
    author_caregiver_guid,
    active_blocks,
    has_sharing_consent,
    emergency_active=False,
):
    """Decide one care-phase read of data authored at
    (author_clinic, author_caregiver) by a reader acting from
    (reader_unit, reader_org).

    Args:
        active_blocks: the patient's ACTIVE PatientBlock rows (callers
            pre-filter with ``is_active()``; lifted blocks are absent).
        has_sharing_consent: patient holds an active PatientConsent for
            the READING caregiver (Zone-3 cohesive-care consent).
        emergency_active: an unexpired EmergencyAccess grant exists for
            (patient, reading unit) — nödöppning.

    Returns:
        (allowed: bool, zone: int, access_basis: str | None,
         reason: str | None) — reason carries the exclusion code when
        allowed is False; access_basis is None on denial.
    """
    zone = zone_for(reader_care_unit_guid, reader_care_organisation_guid,
                    author_clinic_guid, author_caregiver_guid)

    if zone == 1:
        # The authoring unit's own data — spärr never applies inward.
        return True, 1, BASIS_SAME_UNIT, None

    inre = _active_block_on(active_blocks, "clinic", author_clinic_guid)

    if zone == 2:
        if inre and not emergency_active:
            return False, 2, None, REASON_INRE_SPARR
        return True, 2, BASIS_EMERGENCY if inre else BASIS_SAME_ORG, None

    # Zone 3 — cross-organisation.
    yttre = _active_block_on(active_blocks, "caregiver", author_caregiver_guid)
    if emergency_active:
        # Nödöppning overrides both spärr and absent consent (PDL 6:5).
        return True, 3, BASIS_EMERGENCY, None
    if yttre:
        return False, 3, None, REASON_YTTRE_SPARR
    if inre:
        # A clinic block hides that unit's data outside the unit —
        # crossing the org boundary does not weaken it.
        return False, 3, None, REASON_INRE_SPARR
    if not has_sharing_consent:
        return False, 3, None, REASON_NO_SHARING_CONSENT
    return True, 3, BASIS_CROSS_ORG_CONSENT, None


# ======================================================================
# A patient-granted proxy (next of kin) — EPS C3, #889.
#
# This is a NEW AXIS in the access model, not a new value in an existing
# one, which is why it gets its own function and its own basis rather
# than a fourth zone. Everything above answers "may this CARE identity
# read data authored by that care identity?" — every argument is a care
# identity. A relative is not one. There is no care unit, no caregiver
# and no organisation on this side of the question, so zone_for() has
# nothing to classify.
#
# It lives in THIS module anyway, because the docstring at the top claims
# this file is the single source of the access rule "so no two consumers
# may enforce different zone rules". A second access axis decided in a
# decorator somewhere would make that claim false.
#
# WHAT THIS DELIBERATELY DOES NOT DO: it does not consult spärr or
# consent. A patient's own data is never hidden from the patient — spärr
# hides data from OTHER care providers — and a proxy reading as the
# patient inherits exactly the patient's own view. Folding blocks in here
# would give the relative a DIFFERENT view from the patient's, in one
# direction or the other, and neither is what A3 ratified.
# ======================================================================

BASIS_PATIENT_PROXY = "patient_proxy"

REASON_NO_PROXY_GRANT = "no_proxy_grant"
REASON_PROXY_GRANT_INACTIVE = "proxy_grant_inactive"
REASON_PROXY_WRITE_REFUSED = "proxy_write_refused"
REASON_PROXY_ACTION_RESERVED = "proxy_action_reserved_to_patient"

# A proxy is READ-ONLY. This is the #729/#760 lesson stated as code: on
# this platform, twice, an identity added so that it could READ turned
# out to be able to WRITE, because the grant was checked on a read path
# and the writes shared it.
#
# Here the stakes are higher than an over-broad write. The patient
# surface behind ``require_patient`` is not a data surface — it is the
# patient's self-determination controls. Measured 2026-11-02: of the 17
# routes behind the patient identity in ips, TEN are POST, and they are
# create-block, LIFT-block, extend-block, create-consent and
# revoke-consent (×2, JSON and HTML).
#
# So a proxy admitted without a method gate could lift the patient's
# spärr and then read what the spärr was hiding. That is an escalation
# chain, not an over-grant. And A3 forbids it directly: only the patient
# may INCREASE access, and lifting a spärr increases access.
PROXY_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Named actions that are reserved to the patient *categorically* — not
# merely absent from today's scopes. Should a future scope ever grant a
# proxy some write, these must still refuse, so the refusal cannot be
# lost by widening a scope. Belt and braces over PROXY_SAFE_METHODS,
# which already covers them by method.
PROXY_RESERVED_ACTIONS = frozenset({
    "block_create", "block_lift", "block_extend",
    "consent_create", "consent_revoke",
    "proxy_grant_create", "proxy_grant_widen",
})


def evaluate_proxy_access(
    *,
    patient_guid,
    proxy_user_guid,
    grants,
    at=None,
    method="GET",
    action=None,
):
    """Decide one read performed by a proxy acting for ``patient_guid``.

    Args:
        patient_guid: the SUBJECT patient the proxy claims to act for.
        proxy_user_guid: the proxy's sso ``users.guid``.
        grants: the patient's ``PatientProxyGrant`` rows for this proxy,
            in ANY state. Unlike ``active_blocks`` above, these are NOT
            pre-filtered: passing revoked and not-yet-valid rows in is
            what lets this function tell "never granted" from "no longer
            granted", which the audit needs.
        at: evaluation time; defaults to now via ``is_active``.
        method: the HTTP method of the request.
        action: optional named action for the reserved-action check.

    Returns:
        ``(allowed, basis, reason)``. ``basis`` is ``patient_proxy`` on
        success and None on denial; ``reason`` carries the code on
        denial.

    NOTE ON THE TWO DENIAL CODES. ``no_proxy_grant`` and
    ``proxy_grant_inactive`` are different facts and the AUDIT wants
    both. The HTTP response must NOT distinguish them: telling a caller
    "there was a grant, but it is revoked" confirms that this patient
    once named this person, which is exactly the kind of existence leak
    the platform refuses elsewhere (absent, not refused). Callers map
    both to one refusal body and log the precise code.
    """
    if action is not None and action in PROXY_RESERVED_ACTIONS:
        return False, None, REASON_PROXY_ACTION_RESERVED

    if str(method).upper() not in PROXY_SAFE_METHODS:
        return False, None, REASON_PROXY_WRITE_REFUSED

    if not patient_guid or not proxy_user_guid:
        # Missing input falls to the SAFE value, as everywhere above.
        return False, None, REASON_NO_PROXY_GRANT

    pg, px = str(patient_guid), str(proxy_user_guid)
    matching = [
        g for g in grants or []
        if str(g.patient_guid) == pg and str(g.proxy_user_guid) == px
    ]
    if not matching:
        return False, None, REASON_NO_PROXY_GRANT

    if any(g.is_active(at) for g in matching):
        return True, BASIS_PATIENT_PROXY, None

    return False, None, REASON_PROXY_GRANT_INACTIVE


def proxy_mutation_allowed(*, actor_role, mutation):
    """Who may change a proxy grant — EPS A3 (#879), ratified:

        both parties may REDUCE access; only the patient may INCREASE it

    ``actor_role`` is ``'patient'`` or ``'proxy'``; ``mutation`` is
    ``'create'``, ``'widen'`` or ``'revoke'``.

    A relative terminating their own access is A3's fourth clause and is
    deliberately allowed — somebody who no longer wishes to hold access
    to another person's record must be able to put it down without
    asking the patient to act.
    """
    if mutation == "revoke":
        return actor_role in ("patient", "proxy")
    if mutation in ("create", "widen"):
        return actor_role == "patient"
    return False
