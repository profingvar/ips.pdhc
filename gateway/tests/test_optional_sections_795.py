"""#795 — the seven euIPS OPTIONAL sections, and the three traps in them.

1. **Pregnancy must fit sex and age** — and the ticket's warning, taken
   literally, would produce its own error. A CURRENT pregnancy on a male or an
   80-year-old is nonsense; pregnancy HISTORY on an 80-year-old woman is
   perfectly ordinary. The two are gated separately and tested separately.
2. **Past illnesses must not pollute the active problem list.** They share
   `Condition` and are separated only by `clinicalStatus`.
3. **An advance directive is not care consent.** It is a FHIR `Consent` in
   `fhir_resources`, never a `patient_consents` row — that table is cohesive-
   care consent read by `/consents/check`, which request.pdhc and
   contract.pdhc both call.

Plus the discrimination fix this ticket forced: seven sections map to
`Observation`, so an Observation with no `category` is attributable to no
section at all.
"""
from __future__ import annotations

import random

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientIndex
from app.services import euips_optional as opt
from app.services import euips_sections as euips

OPTIONAL_KEYS = ("vital_signs", "past_illnesses", "pregnancy", "social_history",
                 "functional_status", "plan_of_care", "advance_directives")


def _clinic(db):
    c = Clinic(name="Opt Test Clinic", organisation_guid="org-opt-0001",
               identifier="org-opt-0001", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _generate(client, clinic, n):
    resp = client.post("/admin/mock-data",
                       data={"clinic_guid": str(clinic.guid), "count": str(n)},
                       follow_redirects=True)
    assert resp.status_code == 200


def _rows(rtype=None):
    q = _db.session.query(FhirResource)
    if rtype:
        q = q.filter(FhirResource.resource_type == rtype)
    return q.all()


class TestPregnancyConsistency:
    def test_a_male_patient_never_gets_pregnancy_data(self):
        """Either form. This is the ticket's warning."""
        rng = random.Random(1)
        for _ in range(300):
            bodies = opt.optional_sections_for("Patient/p", "1970-05-05",
                                               "male", rng=rng)
            for b in bodies:
                codes = {c.get("code")
                         for c in (b.get("code") or {}).get("coding") or []}
                assert not (codes & euips.PREGNANCY_CODES), b

    def test_unknown_sex_never_gets_pregnancy_data(self):
        rng = random.Random(2)
        for _ in range(200):
            for b in opt.optional_sections_for("Patient/p", "1970-05-05",
                                               None, rng=rng):
                codes = {c.get("code")
                         for c in (b.get("code") or {}).get("coding") or []}
                assert not (codes & euips.PREGNANCY_CODES), b

    def test_a_child_never_gets_pregnancy_data(self):
        rng = random.Random(3)
        for _ in range(200):
            for b in opt.optional_sections_for("Patient/p", "2018-05-05",
                                               "female", rng=rng):
                codes = {c.get("code")
                         for c in (b.get("code") or {}).get("coding") or []}
                assert not (codes & euips.PREGNANCY_CODES), b

    def test_an_elderly_woman_may_have_pregnancy_HISTORY(self):
        """The nuance the ticket's warning hides. Refusing all pregnancy data
        above 50 would be its own error: an 80-year-old woman may well have had
        children, and a summary that denies it is wrong in the other
        direction."""
        current, history = opt.pregnancy_eligibility("female", 80)
        assert current is False, "a current pregnancy at 80 is nonsense"
        assert history is True, "pregnancy history at 80 is ordinary"

    def test_no_current_pregnancy_is_generated_above_the_age_bound(self):
        rng = random.Random(4)
        for _ in range(300):
            for b in opt.optional_sections_for("Patient/p", "1940-05-05",
                                               "female", rng=rng):
                codes = {c.get("code")
                         for c in (b.get("code") or {}).get("coding") or []}
                # Pregnancy STATUS is the current-pregnancy code.
                assert "82810-3" not in codes, b
                assert "77386006" not in str(b), b

    def test_a_woman_of_childbearing_age_can_have_both(self):
        current, history = opt.pregnancy_eligibility("female", 30)
        assert current and history


class TestPastIllnessesDoNotPolluteTheProblemList:
    def test_every_generated_past_illness_is_resolved(self):
        rng = random.Random(5)
        found = 0
        for _ in range(200):
            for b in opt.optional_sections_for("Patient/p", "1960-05-05",
                                               "female", rng=rng):
                if b["resourceType"] == "Condition":
                    found += 1
                    codes = {c["code"] for c in b["clinicalStatus"]["coding"]}
                    assert codes <= {"resolved", "inactive", "remission"}, codes
        assert found, "no past illness was generated"

    def test_a_resolved_condition_is_attributed_to_past_illnesses_only(self, client, db):
        _generate(client, _clinic(db), 25)
        problems = euips.BY_KEY["problems"]
        past = euips.BY_KEY["past_illnesses"]
        for r in _rows("Condition"):
            rj = r.resource_json
            if euips.is_absent_assertion(rj):
                continue
            assert not (euips.section_matches(problems, "Condition", rj)
                        and euips.section_matches(past, "Condition", rj))

    def test_a_patient_with_only_past_illnesses_is_not_conformant(self):
        """THE conformance-affecting bug #795 exposed in #791. Before the
        discriminators, a resolved condition made `problems` read PRESENT, so a
        patient with an empty ACTIVE problem list was called conformant."""
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j
        resolved = Row("Condition", {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": "resolved"}]},
            "code": {"coding": [{"code": "233604007"}]}})
        st = euips.status_for_resources([resolved])
        assert st["past_illnesses"] == euips.PRESENT
        assert st["problems"] == euips.MISSING
        assert euips.is_conformant(st) is False


class TestAdvanceDirectivesAreNotCareConsent:
    def test_a_directive_is_a_fhir_resource_not_a_patient_consent_row(self, client, db):
        """patient_consents is cohesive-care consent (Lag 2022:913 §5), read by
        /consents/check which request.pdhc and contract.pdhc both call. An
        advance directive must not be mistakable for permission to share
        data."""
        _generate(client, _clinic(db), 40)
        consents = _rows("Consent")
        assert consents, "no advance directive generated in 40 patients"
        assert _db.session.query(PatientConsent).count() == 0, \
            "an advance directive leaked into patient_consents"

    def test_the_directive_carries_the_advance_directive_scope(self, client, db):
        _generate(client, _clinic(db), 40)
        for r in _rows("Consent"):
            scope = r.resource_json.get("scope") or {}
            codes = {c.get("code") for c in scope.get("coding") or []}
            assert "adr" in codes, scope

    def test_a_minor_gets_no_advance_directive(self):
        rng = random.Random(6)
        for _ in range(200):
            for b in opt.optional_sections_for("Patient/p", "2015-01-01",
                                               "female", rng=rng):
                assert b["resourceType"] != "Consent", b


class TestObservationSectionsAreDistinguishable:
    def test_every_generated_observation_carries_a_category(self):
        """Seven sections map to Observation. One with no category is
        attributable to no section at all -- which is what the old
        _mock_patient_resources emitted."""
        rng = random.Random(7)
        found = 0
        for _ in range(100):
            for b in opt.optional_sections_for("Patient/p", "1970-05-05",
                                               "female", rng=rng):
                if b["resourceType"] == "Observation":
                    found += 1
                    assert b.get("category"), b
        assert found

    def test_a_vital_sign_does_not_claim_six_other_sections(self, client, db):
        """The #791 over-reporting bug, from the reading side."""
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j
        vs = Row("Observation", {
            "resourceType": "Observation",
            "category": [{"coding": [{"code": "vital-signs"}]}],
            "code": {"coding": [{"code": "8867-4"}]},
            "subject": {"reference": "Patient/p"}})
        st = euips.status_for_resources([vs])
        present = [k for k, v in st.items() if v == euips.PRESENT]
        assert present == ["vital_signs"], present

    def test_every_section_sharing_a_type_has_a_discriminator(self):
        """Structural guard: if a new section is added that shares Observation
        or Condition without a discriminator, it will silently claim every
        other section's resources."""
        from collections import defaultdict
        shared = defaultdict(list)
        for s in euips.SECTIONS:
            for t in s.resource_types:
                shared[t].append(s)
        for rtype, secs in shared.items():
            if len(secs) > 1:
                for s in secs:
                    assert s.discriminator, \
                        f"{s.key} shares {rtype} with {len(secs)-1} others " \
                        f"and has no discriminator"

    def test_an_ordinary_social_history_observation_is_not_travel_history(self):
        """#795 asserted `TRAVEL_CODES == frozenset()` here, because no code
        was established and a guess would have made the section claim
        observations that are not travel history. **#796 settled the code
        provisionally**, so that assertion became false for a correct reason —
        the same shape as #793's problem-list test.

        What survives is the invariant that actually matters: a smoking-status
        observation is social history and NOT travel history, whatever
        TRAVEL_CODES happens to contain. The "is it still unverified" question
        is pinned in #796's own tests, where the decision lives.
        """
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j
        obs = Row("Observation", {"resourceType": "Observation",
                                  "category": [{"coding": [{"code": "social-history"}]}],
                                  "code": {"coding": [{"code": "72166-2"}]}})
        st = euips.status_for_resources([obs])
        assert st["travel_history"] == euips.MISSING
        assert st["social_history"] == euips.PRESENT
        # And the codes remain flagged unverified, wherever they are set.
        assert euips.CODES_VERIFIED is False


class TestOptionalMeansOptional:
    def test_sections_are_absent_for_some_patients(self, client, db):
        """Optional sections present for EVERY patient would be less useful for
        testing than a realistic mix."""
        rng = random.Random(8)
        counts = {k: 0 for k in OPTIONAL_KEYS}
        class Row:
            def __init__(s, t, j):
                s.resource_type, s.resource_json = t, j
        N = 150
        for _ in range(N):
            bodies = opt.optional_sections_for(
                "Patient/p", f"{rng.randint(1935, 2015)}-05-05",
                rng.choice(["male", "female"]), rng=rng)
            st = euips.status_for_resources(
                [Row(b["resourceType"], b) for b in bodies])
            for k in OPTIONAL_KEYS:
                if st[k] == euips.PRESENT:
                    counts[k] += 1
        for k, n in counts.items():
            assert 0 < n < N, f"{k} present in {n}/{N} -- not actually optional"

    def test_conformance_is_unaffected_by_optional_sections(self, client, db):
        _generate(client, _clinic(db), 25)
        for p in _db.session.query(PatientIndex).all():
            rows = (_db.session.query(FhirResource)
                    .filter(FhirResource.patient_guid == p.guid).all())
            st = euips.status_for_resources(rows)
            assert euips.is_conformant(st), {k: st[k] for k in euips.REQUIRED_KEYS}
