"""#906 — EPS and IPS require different section sets.

#885 fetched `composition-eu-eps` and found that every section CODE
agrees with this catalogue and two OBLIGATIONS do not: EPS makes
`sectionProceduresHx` (47519-4) and `sectionMedicalDevices` (46264-8)
**1..1**, where this catalogue has both RECOMMENDED for the domestic IPS
surface it serves day to day.

One catalogue cannot hold two obligation sets by overwriting one of them,
so it holds both — and `is_conformant` takes the profile as a
KEYWORD-ONLY argument WITH NO DEFAULT.

That last part is the design decision, and it is worth stating why,
because a default would have been less disruptive and much worse. The
failure mode to protect against is not a wrong answer. It is a caller
who never noticed there were two questions and silently received the
other one's answer — and a default protects exactly the callers written
before the second profile existed, which are the ones that have never
been reviewed for it. Making the argument mandatory broke ten call sites
and three of them turned out to be making a claim that was true of one
profile and false of the other.

Same lesson as #779 (two identifier spaces compared as if they were one)
and #760 (a read allowlist that also granted writes): where two things
can be confused, make the code say which one it means.
"""
from __future__ import annotations

import uuid

import pytest

from app.services import euips_report, euips_sections as euips

#: `Composition.section` is **5..\*** in composition-eu-eps, fetched
#: 2026-11-02. This is the figure the per-section comparison cannot give.
EPS_PUBLISHED_MIN_SECTIONS = 5

DIVERGENT = ("procedures", "devices")


def _status(**over):
    """A status map with everything MISSING unless named."""
    st = {s.key: euips.MISSING for s in euips.SECTIONS}
    st.update(over)
    return st


def _ips_complete():
    return _status(**{k: euips.PRESENT
                      for k in euips.required_keys(euips.PROFILE_IPS)})


class TestTheTwoRequiredSets:
    def test_ips_requires_three(self):
        assert euips.required_keys(euips.PROFILE_IPS) == (
            "allergies", "problems", "medications")

    def test_eps_requires_those_three_PLUS_procedures_and_devices(self):
        eps = euips.required_keys(euips.PROFILE_EPS)
        ips = euips.required_keys(euips.PROFILE_IPS)
        assert set(ips) < set(eps), "EPS must be a superset, not a variant"
        assert set(eps) - set(ips) == set(DIVERGENT)

    def test_THE_CROSS_CHECK_eps_required_count_matches_the_published_5(self):
        """The one assertion the per-section comparison cannot make.

        #906 asked for this explicitly: `Composition.section` is 5..* in the
        published profile, and that single number is what catches a future
        ballot adding a SIXTH required section — a change that a
        code-by-code comparison would pass, because every code it checks
        would still be correct.
        """
        assert len(euips.required_keys(euips.PROFILE_EPS)) == \
            EPS_PUBLISHED_MIN_SECTIONS

    def test_the_legacy_name_still_means_IPS(self):
        """`REQUIRED_KEYS` is read over the API and in four modules. It keeps
        its original meaning so no caller is silently re-answered."""
        assert euips.REQUIRED_KEYS == euips.required_keys(euips.PROFILE_IPS)


class TestOnlyTheDivergenceIsWrittenDown:
    @pytest.mark.parametrize("key", DIVERGENT)
    def test_the_two_divergent_sections_carry_obligation_eps(self, key):
        s = euips.BY_KEY[key]
        assert s.obligation == euips.RECOMMENDED
        assert s.obligation_eps == euips.REQUIRED

    def test_every_OTHER_section_leaves_it_None(self):
        """None means "the same", so a reader finds the two divergences
        instead of comparing seventeen identical pairs."""
        for s in euips.SECTIONS:
            if s.key not in DIVERGENT:
                assert s.obligation_eps is None, s.key

    def test_obligation_for_resolves_None_to_the_base_obligation(self):
        allergies = euips.BY_KEY["allergies"]
        assert allergies.obligation_for == {
            euips.PROFILE_IPS: euips.REQUIRED,
            euips.PROFILE_EPS: euips.REQUIRED,
        }
        devices = euips.BY_KEY["devices"]
        assert devices.obligation_for[euips.PROFILE_IPS] == euips.RECOMMENDED
        assert devices.obligation_for[euips.PROFILE_EPS] == euips.REQUIRED

    def test_the_CODES_agree_even_though_the_obligations_do_not(self):
        """What #885 established, pinned here because it is the reason this
        is an obligation problem and not a terminology one."""
        assert euips.BY_KEY["procedures"].loinc == "47519-4"
        assert euips.BY_KEY["devices"].loinc == "46264-8"


class TestTheProfileCannotBeOmitted:
    def test_calling_without_a_profile_is_a_TypeError(self):
        """The design decision, asserted. A default would have protected the
        callers written before the second profile existed — which are exactly
        the ones that have never been reviewed for it."""
        with pytest.raises(TypeError):
            euips.is_conformant(_ips_complete())

    def test_it_cannot_be_passed_positionally_either(self):
        with pytest.raises(TypeError):
            euips.is_conformant(_ips_complete(), euips.PROFILE_EPS)

    @pytest.mark.parametrize("bad", ["", "IPS", "ips ", "eu", None, "epss"])
    def test_an_unknown_profile_RAISES_rather_than_matching_nothing(
            self, bad):
        """An empty required set makes EVERY patient conformant, which is the
        one wrong answer that looks like good news."""
        with pytest.raises(ValueError):
            euips.required_keys(bad)
        with pytest.raises(ValueError):
            euips.is_conformant(_ips_complete(), profile=bad)


class TestTheTwoAnswersDiffer:
    def test_an_ips_complete_patient_is_NOT_eps_conformant(self):
        st = _ips_complete()
        assert euips.is_conformant(st, profile=euips.PROFILE_IPS) is True
        assert euips.is_conformant(st, profile=euips.PROFILE_EPS) is False

    def test_adding_the_two_sections_makes_it_eps_conformant_too(self):
        st = _ips_complete()
        for k in DIVERGENT:
            st[k] = euips.PRESENT
        assert euips.is_conformant(st, profile=euips.PROFILE_EPS) is True

    def test_EXPLICITLY_ABSENT_satisfies_EPS_as_it_does_IPS(self):
        """EPS makes the sections 1..1; it does not make them non-empty. An
        explicit "no known devices" is a present section, which is the whole
        reason the absent codes exist."""
        st = _ips_complete()
        for k in DIVERGENT:
            st[k] = euips.EXPLICITLY_ABSENT
        assert euips.is_conformant(st, profile=euips.PROFILE_EPS) is True

    @pytest.mark.parametrize("missing", DIVERGENT)
    def test_either_one_missing_is_enough_to_fail_EPS(self, missing):
        st = _ips_complete()
        for k in DIVERGENT:
            st[k] = euips.PRESENT
        st[missing] = euips.MISSING
        assert euips.is_conformant(st, profile=euips.PROFILE_EPS) is False
        assert euips.is_conformant(st, profile=euips.PROFILE_IPS) is True

    def test_conformance_returns_both_with_the_missing_lists(self):
        st = _ips_complete()
        c = euips.conformance(st)
        assert set(c) == set(euips.PROFILES)
        assert c[euips.PROFILE_IPS]["conformant"] is True
        assert c[euips.PROFILE_IPS]["required_missing"] == []
        assert c[euips.PROFILE_EPS]["conformant"] is False
        assert set(c[euips.PROFILE_EPS]["required_missing"]) == set(DIVERGENT)


class TestTheSurfacesSayWhichProfile:
    def test_the_report_counts_BOTH(self, client, db):
        r = euips_report.report()
        assert set(r["conformant_by_profile"]) == set(euips.PROFILES)
        assert r["required_by_profile"][euips.PROFILE_IPS] == \
            list(euips.required_keys(euips.PROFILE_IPS))
        assert len(r["required_by_profile"][euips.PROFILE_EPS]) == \
            EPS_PUBLISHED_MIN_SECTIONS

    def test_the_text_report_names_the_profiles(self, client, db):
        text = euips_report.format_report(euips_report.report())
        assert "conformant by profile" in text
        assert "ips=" in text and "eps=" in text

    def test_the_endpoint_says_WHICH_profile_its_conformant_field_means(
            self, client, db):
        from app.models.fhir_resource import FhirResource
        from app.models.patient_index import PatientIndex
        fhir = FhirResource(resource_type="Patient",
                            resource_id=str(uuid.uuid4()),
                            resource_json={"resourceType": "Patient"})
        db.session.add(fhir)
        db.session.flush()
        p = PatientIndex(fhir_resource_guid=fhir.guid,
                         resource_id=str(uuid.uuid4()),
                         family_name="Profilsson", given_name="Test")
        db.session.add(p)
        db.session.commit()

        r = client.get(f"/api/v1/patients/{p.guid}/euips-sections")
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        # The old field keeps its value AND now names its profile.
        assert body["conformant_profile"] == euips.PROFILE_IPS
        assert body["conformant"] == \
            body["conformance"][euips.PROFILE_IPS]["conformant"]
        # Both answers are available without a second call.
        assert set(body["conformance"]) == set(euips.PROFILES)

    def test_the_endpoint_shows_obligation_eps_only_where_it_differs(
            self, client, db):
        from app.models.fhir_resource import FhirResource
        from app.models.patient_index import PatientIndex
        fhir = FhirResource(resource_type="Patient",
                            resource_id=str(uuid.uuid4()),
                            resource_json={"resourceType": "Patient"})
        db.session.add(fhir)
        db.session.flush()
        p = PatientIndex(fhir_resource_guid=fhir.guid,
                         resource_id=str(uuid.uuid4()),
                         family_name="Profilsson", given_name="Test2")
        db.session.add(p)
        db.session.commit()

        body = client.get(
            f"/api/v1/patients/{p.guid}/euips-sections").get_json()
        by_key = {s["key"]: s for s in body["sections"]}
        for k in DIVERGENT:
            assert by_key[k]["obligation_eps"] == euips.REQUIRED
        assert by_key["allergies"]["obligation_eps"] is None
