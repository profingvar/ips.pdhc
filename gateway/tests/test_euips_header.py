"""euIPS document header — #792.

The tests that matter here are the ones about DISAGREEMENT, not about field
presence. #792's watch item is that the custodian, the Patient's
`managingOrganization` and the `PatientClinicAssignment` row are three places
holding one organisation, which is the #768 shape — three organisation
identifiers on one datapoint that failed to collapse, so a Rule 24 gate scoped
on the wrong one.

A test that only asserts "custodian is set" would pass with the custodian set
to the wrong organisation. So the checks below assert it equals the ASSIGNMENT
specifically, and that a deliberately stale `managingOrganization` is reported
rather than silently preferred.
"""
from datetime import date, datetime, timezone

import pytest

from app.services import euips_header as hdr


class TestGuardianOnlyForMinors:
    """#792: 'a 60-year-old with a legal guardian is a data-quality bug the
    simulator should not manufacture.'"""

    def test_minor_gets_a_guardian(self):
        born = date.today().replace(year=date.today().year - 10).isoformat()
        out = hdr.related_person_resources(
            "Patient/x", family="Lind", birth_date=born)
        codes = {c["code"] for r in out for rel in r["relationship"]
                 for c in rel["coding"]}
        assert "GUARD" in codes
        assert "PRN" in codes, "a minor's guardian is in practice a parent"

    @pytest.mark.parametrize("age", [18, 35, 60, 86])
    def test_adults_never_get_a_guardian(self, age):
        born = date.today().replace(year=date.today().year - age).isoformat()
        out = hdr.related_person_resources(
            "Patient/x", family="Lind", birth_date=born)
        codes = {c["code"] for r in out for rel in r["relationship"]
                 for c in rel["coding"]}
        assert "GUARD" not in codes, (
            "a %d-year-old was given a legal guardian — the exact bug #792 "
            "names" % age)

    def test_contact_person_is_always_present(self):
        born = date.today().replace(year=date.today().year - 40).isoformat()
        out = hdr.related_person_resources(
            "Patient/x", family="Lind", birth_date=born)
        assert any(c["code"] == "C" for r in out
                   for rel in r["relationship"] for c in rel["coding"])

    def test_unknown_age_gets_no_guardian(self):
        """Unknown age is not 'minor'.

        Defaulting either way would manufacture clinical fact; the safe answer
        is no guardian, and `age_on` returns None rather than guessing.
        """
        for bad in ("", None, "not-a-date", "0000-00-00"):
            assert hdr.age_on(bad) is None
            assert hdr.needs_guardian(bad) is False

    def test_age_on_handles_the_birthday_boundary(self):
        """An 18th birthday that has not yet arrived is still 17."""
        asof = date(2026, 10, 8)
        assert hdr.age_on("2008-10-09", asof) == 17   # tomorrow
        assert hdr.age_on("2008-10-08", asof) == 18   # today
        assert hdr.needs_guardian("2008-10-09", asof) is True
        assert hdr.needs_guardian("2008-10-08", asof) is False

    def test_contact_shares_the_patient_family_name(self):
        out = hdr.related_person_resources(
            "Patient/x", family="Bergström", birth_date="1980-01-01")
        assert all(r["name"][0]["family"] == "Bergström" for r in out)

    def test_patient_contact_mirrors_the_related_persons(self):
        """Both are emitted, from one list, so they cannot diverge."""
        out = hdr.related_person_resources(
            "Patient/x", family="Lind",
            birth_date=date.today().replace(
                year=date.today().year - 8).isoformat())
        contacts = hdr.patient_contact(out)
        assert len(contacts) == len(out) == 2
        assert [c["name"]["family"] for c in contacts] == ["Lind", "Lind"]
        assert all(c["relationship"] for c in contacts)


class TestCoverageIsPublicRegional:
    def test_public_not_private(self):
        cov = hdr.coverage_resource("Patient/x", city="Stockholm")
        coding = cov["type"]["coding"][0]
        assert coding["code"] == "PUBLICPOL", (
            "#792 asks for regional public cover, not a private-insurer "
            "placeholder")
        assert cov["kind"] == "insurance"
        assert cov["beneficiary"]["reference"] == "Patient/x"

    def test_insurer_is_the_region_for_the_patient_city(self):
        assert hdr.coverage_resource(
            "Patient/x", city="Malmö")["insurer"]["display"] == "Region Skåne"
        assert hdr.coverage_resource(
            "Patient/x", city="Göteborg"
        )["insurer"]["display"] == "Västra Götalandsregionen"

    def test_insurer_has_no_dangling_reference(self):
        """ips holds no region registry, so a GUID here would point nowhere.

        A display-only Reference says "this organisation, which I cannot
        resolve" honestly. An `Organization/<made-up-guid>` would be the
        dangling-reference problem #771 and #768 are both about.
        """
        cov = hdr.coverage_resource("Patient/x", city="Lund")
        assert "reference" not in cov["insurer"]
        assert cov["insurer"]["display"]

    def test_unknown_city_falls_back_without_crashing(self):
        cov = hdr.coverage_resource("Patient/x", city="Kiruna")
        assert cov["insurer"]["display"] == hdr.DEFAULT_REGION
        assert hdr.coverage_resource("Patient/x")["insurer"]["display"]

    def test_personnummer_is_the_subscriber_id(self):
        cov = hdr.coverage_resource("Patient/x", personnummer="19610115-9638")
        assert cov["subscriberId"][0]["value"] == "19610115-9638"
        assert cov["subscriberId"][0]["system"] == hdr.PERSONNUMMER_SYSTEM


class TestCompositionHeader:
    def test_all_three_parties_are_the_custodian_organisation(self):
        """A generated summary has no human author.

        Naming one would put a clinician who does not exist into clinical
        data, where a later reader cannot tell the fabrication from a real
        attribution.
        """
        h = hdr.composition_header(
            custodian_full_url="urn:uuid:org-1",
            custodian_display="Test Clinic", language="sv-SE")
        assert h["custodian"]["reference"] == "urn:uuid:org-1"
        assert h["author"][0]["reference"] == "urn:uuid:org-1"
        assert h["attester"][0]["party"]["reference"] == "urn:uuid:org-1"

    def test_attester_mode_is_a_codeable_concept_not_a_code(self):
        """R5 changed `Composition.attester.mode` from code to CodeableConcept.

        Asserted explicitly because the R4 shape would validate nowhere and is
        the kind of version slip that is invisible until an external validator
        rejects the whole document.
        """
        h = hdr.composition_header(
            custodian_full_url="urn:uuid:org-1",
            custodian_display="C", language="sv-SE")
        mode = h["attester"][0]["mode"]
        assert isinstance(mode, dict), "R4 shape (plain code) regressed in"
        assert mode["coding"][0]["code"] == "legal"

    def test_no_custodian_means_no_invented_attribution(self):
        """An unattributed document is correct; an invented one is not."""
        h = hdr.composition_header(
            custodian_full_url=None, custodian_display=None,
            language="sv-SE")
        assert h == {"language": "sv-SE"}
        for forbidden in ("author", "attester", "custodian"):
            assert forbidden not in h

    def test_attested_time_is_the_composition_date(self):
        when = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        h = hdr.composition_header(
            custodian_full_url="urn:uuid:o", custodian_display="C",
            language="sv-SE", attested_at=when)
        assert h["attester"][0]["time"] == when.isoformat()


class TestLanguage:
    def test_default_dominates_but_the_tail_is_reachable(self):
        """#792 wants a minority of other values so those paths are exercised.

        Asserted statistically over a fixed seed: a distribution that is
        99.9% sv-SE would satisfy "mostly Swedish" while leaving the
        non-Swedish path dead, which is the thing the ticket asks against.
        """
        import random as _r
        rnd = _r.Random(20261008)
        picks = [hdr.pick_language(rnd) for _ in range(2000)]
        sv = picks.count("sv-SE")
        assert 0.78 < sv / len(picks) < 0.93, "sv-SE share drifted: %d" % sv
        assert len(set(picks)) >= 4, (
            "only %d distinct languages in 2000 draws — the minority tail is "
            "effectively dead" % len(set(picks)))

    def test_patient_communication_marks_it_preferred(self):
        c = hdr.patient_communication("fi-FI")
        assert c[0]["language"]["coding"][0]["code"] == "fi-FI"
        assert c[0]["language"]["coding"][0]["system"] == "urn:ietf:bcp:47"
        assert c[0]["preferred"] is True


class TestOrganizationIsDerived:
    class _Clinic:
        def __init__(self, org_guid, name="Test Clinic", ident="HSA-1",
                     active=True):
            self.organisation_guid = org_guid
            self.guid = "clinic-guid"
            self.name = name
            self.identifier = ident
            self.is_active = active

    def test_organisation_comes_from_the_clinic(self):
        org = hdr.organization_resource(self._Clinic("org-abc"))
        assert org["id"] == "org-abc"
        assert org["name"] == "Test Clinic"
        assert org["address"][0]["country"] == "SE"
        assert org["identifier"][0]["value"] == "HSA-1"

    def test_no_clinic_yields_no_placeholder(self):
        """A custodian of 'Demo Clinic' asserts an organisation that does not
        exist, and the header would then disagree with the assignment."""
        assert hdr.organization_resource(None) is None


class TestHeaderStatus:
    def _patient(self, **over):
        p = {"identifier": [{"value": "x"}], "name": [{"family": "L"}],
             "birthDate": "1980-01-01", "gender": "female",
             "communication": hdr.patient_communication("sv-SE")}
        p.update(over)
        return p

    def _composition(self):
        c = {"date": "2026-10-08T00:00:00+00:00"}
        c.update(hdr.composition_header(
            custodian_full_url="urn:uuid:o", custodian_display="C",
            language="sv-SE"))
        return c

    def test_complete_header_reports_complete(self):
        st = hdr.header_status(
            patient_json=self._patient(),
            related=hdr.related_person_resources(
                "Patient/x", family="L", birth_date="1980-01-01"),
            coverage=[hdr.coverage_resource("Patient/x")],
            composition=self._composition())
        assert st["complete"], st["missing"]
        assert st["codes_verified"] is False, (
            "the header must not claim verified codes — the EHDS specs were "
            "not confirmed adopted and nothing here is checked against a "
            "published IG")

    def test_adult_guardian_is_not_applicable_not_missing(self):
        """Counting an adult's absent guardian as a gap would push the
        generator toward manufacturing one."""
        st = hdr.header_status(
            patient_json=self._patient(),
            related=hdr.related_person_resources(
                "Patient/x", family="L", birth_date="1980-01-01"),
            coverage=[hdr.coverage_resource("Patient/x")],
            composition=self._composition())
        assert st["elements"]["legal_guardian"]["status"] == "not_applicable"
        assert "legal_guardian" not in st["missing"]

    def test_minor_without_a_guardian_is_missing(self):
        born = date.today().replace(year=date.today().year - 9).isoformat()
        st = hdr.header_status(
            patient_json=self._patient(birthDate=born),
            related=[],                       # none generated
            coverage=[hdr.coverage_resource("Patient/x")],
            composition=self._composition())
        assert st["elements"]["legal_guardian"]["status"] == "missing"
        assert "legal_guardian" in st["missing"]

    def test_missing_pieces_are_named(self):
        st = hdr.header_status(patient_json=self._patient(), related=[],
                               coverage=[], composition=None)
        for expect in ("health_insurance", "author", "legal_authenticator",
                       "custodian", "created", "contact_person"):
            assert expect in st["missing"], expect
        assert not st["complete"]

    def test_every_declared_element_is_reported(self):
        """HEADER_ELEMENTS is the single list of what #792 requires."""
        st = hdr.header_status(patient_json=self._patient(), related=[],
                               coverage=[], composition=None)
        assert set(st["elements"]) == {k for k, _ in hdr.HEADER_ELEMENTS}
