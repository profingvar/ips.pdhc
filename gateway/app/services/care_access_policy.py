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
