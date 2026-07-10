"""D3 (#406) — unit tests for the composed care-phase zone rule.

Pure policy: no db, no Flask. Blocks are stubbed with the two fields
the policy reads (source_scope_type, source_scope_id).
"""
from types import SimpleNamespace

from app.services.care_access_policy import (
    BASIS_CROSS_ORG_CONSENT,
    BASIS_EMERGENCY,
    BASIS_SAME_ORG,
    BASIS_SAME_UNIT,
    REASON_INRE_SPARR,
    REASON_NO_SHARING_CONSENT,
    REASON_YTTRE_SPARR,
    evaluate_care_access,
    zone_for,
)

UNIT_A1 = "unit-a1"     # authoring unit
UNIT_A2 = "unit-a2"     # sibling unit, same org
ORG_A = "org-a"
UNIT_B1 = "unit-b1"     # unit at another org
ORG_B = "org-b"


def _block(scope_type, scope_id):
    return SimpleNamespace(source_scope_type=scope_type,
                           source_scope_id=scope_id)


def _eval(reader_unit, reader_org, *, blocks=(), consent=False,
          emergency=False):
    return evaluate_care_access(
        reader_care_unit_guid=reader_unit,
        reader_care_organisation_guid=reader_org,
        author_clinic_guid=UNIT_A1,
        author_caregiver_guid=ORG_A,
        active_blocks=list(blocks),
        has_sharing_consent=consent,
        emergency_active=emergency,
    )


# --- zone classification ------------------------------------------------

def test_zone_classification():
    assert zone_for(UNIT_A1, ORG_A, UNIT_A1, ORG_A) == 1
    assert zone_for(UNIT_A2, ORG_A, UNIT_A1, ORG_A) == 2
    assert zone_for(UNIT_B1, ORG_B, UNIT_A1, ORG_A) == 3
    # unknown relationships fall to the strictest zone
    assert zone_for(UNIT_B1, None, UNIT_A1, None) == 3


# --- Zone 1: the authoring unit itself ----------------------------------

def test_zone1_always_allowed_even_with_blocks():
    allowed, zone, basis, reason = _eval(
        UNIT_A1, ORG_A,
        blocks=[_block("clinic", UNIT_A1), _block("caregiver", ORG_A)])
    assert (allowed, zone, basis, reason) == (True, 1, BASIS_SAME_UNIT, None)


# --- Zone 2: inre sekretess ----------------------------------------------

def test_zone2_allowed_without_block():
    allowed, zone, basis, reason = _eval(UNIT_A2, ORG_A)
    assert (allowed, zone, basis, reason) == (True, 2, BASIS_SAME_ORG, None)


def test_zone2_blocked_by_inre_sparr():
    allowed, zone, basis, reason = _eval(
        UNIT_A2, ORG_A, blocks=[_block("clinic", UNIT_A1)])
    assert (allowed, zone, basis, reason) == (False, 2, None,
                                              REASON_INRE_SPARR)


def test_zone2_caregiver_block_does_not_bite_inside_the_org():
    # Yttre spärr hides the caregiver's data from OTHER caregivers;
    # within the org only the clinic-scoped inre spärr applies.
    allowed, zone, basis, _ = _eval(
        UNIT_A2, ORG_A, blocks=[_block("caregiver", ORG_A)])
    assert (allowed, zone, basis) == (True, 2, BASIS_SAME_ORG)


def test_zone2_emergency_overrides_inre_sparr():
    allowed, zone, basis, reason = _eval(
        UNIT_A2, ORG_A, blocks=[_block("clinic", UNIT_A1)], emergency=True)
    assert (allowed, zone, basis, reason) == (True, 2, BASIS_EMERGENCY, None)


# --- Zone 3: sammanhållen vård (Lag 2022:913 §5) -------------------------

def test_zone3_requires_consent():
    allowed, zone, basis, reason = _eval(UNIT_B1, ORG_B, consent=False)
    assert (allowed, zone, basis, reason) == (False, 3, None,
                                              REASON_NO_SHARING_CONSENT)


def test_zone3_consent_alone_allows():
    allowed, zone, basis, reason = _eval(UNIT_B1, ORG_B, consent=True)
    assert (allowed, zone, basis, reason) == (True, 3,
                                              BASIS_CROSS_ORG_CONSENT, None)


def test_zone3_yttre_sparr_beats_consent():
    allowed, zone, basis, reason = _eval(
        UNIT_B1, ORG_B, consent=True, blocks=[_block("caregiver", ORG_A)])
    assert (allowed, zone, basis, reason) == (False, 3, None,
                                              REASON_YTTRE_SPARR)


def test_zone3_inre_sparr_also_hides_across_orgs():
    allowed, zone, basis, reason = _eval(
        UNIT_B1, ORG_B, consent=True, blocks=[_block("clinic", UNIT_A1)])
    assert (allowed, zone, basis, reason) == (False, 3, None,
                                              REASON_INRE_SPARR)


def test_zone3_emergency_overrides_sparr_and_missing_consent():
    allowed, zone, basis, reason = _eval(
        UNIT_B1, ORG_B, consent=False,
        blocks=[_block("caregiver", ORG_A), _block("clinic", UNIT_A1)],
        emergency=True)
    assert (allowed, zone, basis, reason) == (True, 3, BASIS_EMERGENCY, None)


def test_blocks_on_other_scopes_do_not_bite():
    allowed, _, basis, _ = _eval(
        UNIT_B1, ORG_B, consent=True,
        blocks=[_block("clinic", "unit-elsewhere"),
                _block("caregiver", "org-elsewhere")])
    assert (allowed, basis) == (True, BASIS_CROSS_ORG_CONSENT)
