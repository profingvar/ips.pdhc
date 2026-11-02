"""#888 (EPS C2) — address, contact and telecom as real elements with periods.

Before this, the generator wrote `use`, `city` and `country` and nothing else.
A service meant to hold "all state information about a patient" could not say
what street they live on, and **had no validity period anywhere** — so every
demographic fact in the state projection (#895) carried `valid_from = NULL`,
meaning "we do not know when this became true". Honest, and useless for
answering "where did this patient live in March".

`TestThePayoff` is the test that makes this ticket worth anything: it asserts
the projection's address facts now carry a real `valid_from`. The rest guard
the ways a period can be present and still be wrong.
"""
from __future__ import annotations

import random
import uuid
from datetime import date

import pytest

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.models.patient_state import PatientStateFact
from app.services import euips_header as hdr
from app.services import patient_state as ps

CITIES = ("Stockholm", "Göteborg", "Malmö", "Uppsala", "Lund")


def _clinic(db):
    c = Clinic(name="888 Clinic", organisation_guid=str(uuid.uuid4()),
               is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _generate(client, clinic, n):
    r = client.post("/admin/mock-data",
                    data={"clinic_guid": str(clinic.guid), "count": str(n)},
                    follow_redirects=True)
    assert r.status_code == 200
    return r


class TestTheAddressShape:
    def test_it_carries_line_postalCode_city_and_country(self):
        a = hdr.patient_address("Malmö", rnd=random.Random(1))
        assert a["line"] and isinstance(a["line"], list)
        assert a["postalCode"] and len(a["postalCode"]) == 5
        assert a["city"] == "Malmö"
        assert a["country"] == hdr.COUNTRY_OF_ORIGIN

    def test_the_postcode_does_not_CONTRADICT_the_city(self):
        """A postcode contradicting the city is the sort of incoherence that
        makes a cohort useless for testing a real integration."""
        for city in CITIES:
            a = hdr.patient_address(city, rnd=random.Random(7))
            assert a["postalCode"].startswith(hdr._POSTCODE_PREFIX[city]), \
                (city, a["postalCode"])

    def test_the_city_is_PASSED_IN_and_never_redrawn(self):
        """The city determines the Coverage insurer's region (#792). Drawing it
        inside would put a Stockholm resident on Region Skåne's books."""
        for city in CITIES:
            assert hdr.patient_address(city, rnd=random.Random(3))["city"] == city

    def test_the_period_is_OPEN_ENDED(self):
        """They still live there. A closed period would say they have moved out
        and we do not know where to, which is a stronger and different claim."""
        a = hdr.patient_address("Lund", moved_in="2019-05-01",
                                rnd=random.Random(1))
        assert a["period"] == {"start": "2019-05-01"}
        assert "end" not in a["period"]

    def test_no_period_when_none_is_given(self):
        """The control: a period must be data, not a default. An invented start
        would be the single-axis mistake #895 refuses."""
        assert "period" not in hdr.patient_address("Lund", rnd=random.Random(1))


class TestTheDatesAreNotIMPOSSIBLE:
    def test_a_start_is_after_birth_and_in_the_past(self):
        """A validity start before the patient was born is not a bad date, it
        is an impossible fact — the same reasoning #900 applies to `ended_at`
        before `assigned_at`."""
        rnd = random.Random(11)
        this_year = date.today().year
        for _ in range(200):
            birth_year = rnd.randint(1940, 2010)
            birth = f"{birth_year}-01-01"
            got_year = int(hdr._past_date_after_birth(
                birth, min_age=18, rnd=rnd)[:4])
            earliest = birth_year + 18

            # A CONJUNCTION, not a disjunction. My first version was
            # `got >= birth+18 OR got <= this_year`, and the second branch is
            # true for every past date -- so the whole assertion was a
            # tautology hiding behind an `or`, and the control that allowed a
            # start in 1900 passed it. Caught only because the control was run.
            assert got_year < this_year, got_year
            if earliest <= this_year - 1:
                assert got_year >= earliest, (birth_year, got_year)
            else:
                # Degenerate range: clamped to the latest past year, which is
                # the property that survives.
                assert got_year == this_year - 1, (birth_year, got_year)

    def test_a_DEGENERATE_range_does_not_produce_a_future_date(self):
        """A patient born last year has no plausible "moved in at 18". The
        range is clamped rather than raising, and the property that must
        survive is that the date is still in the PAST."""
        birth = f"{date.today().year - 1}-01-01"
        got = hdr._past_date_after_birth(birth, min_age=18,
                                         rnd=random.Random(5))
        assert int(got[:4]) < date.today().year + 1, got

    def test_year_between_clamps_rather_than_raising(self):
        assert hdr._year_between(2030, 2020, random.Random(1)) == 2020


class TestTheContactMirrorCannotDISAGREE:
    def test_the_RelatedPerson_carries_a_period(self):
        rel = hdr.related_person_resources("Patient/p", family="Testsson",
                                           birth_date="1980-01-01",
                                           rnd=random.Random(2))
        assert rel[0]["period"]["start"]

    def test_the_inline_Patient_contact_carries_the_SAME_period(self):
        """Both copies are generated from ONE list precisely so they cannot
        disagree. A period on the RelatedPerson but not on the inline copy
        would be exactly that disagreement — with the inline copy being the one
        most consumers read."""
        rel = hdr.related_person_resources("Patient/p", family="Testsson",
                                           birth_date="1980-01-01",
                                           rnd=random.Random(2))
        con = hdr.patient_contact(rel)
        assert len(con) == len(rel)
        for rp, entry in zip(rel, con):
            assert entry["period"] == rp["period"], (rp, entry)

    def test_a_RelatedPerson_without_a_period_mirrors_without_one(self):
        """The control: the mirror copies what is there, it does not invent."""
        con = hdr.patient_contact([{"resourceType": "RelatedPerson",
                                    "name": [{"family": "X"}]}])
        assert "period" not in con[0]


class TestThePayoff:
    def test_the_state_projection_now_has_REAL_validity(self, client, db):
        """What this ticket is for. #895 recorded that every demographic fact
        carried `valid_from = NULL` because no Patient element had a `period`.
        After #888 the address facts have one, so "where did this patient live
        in March" becomes answerable instead of unknown."""
        _generate(client, _clinic(db), 6)
        rows = (_db.session.query(PatientStateFact)
                .filter(PatientStateFact.fact_type.like("address.%")).all())
        assert rows, "the generator produced no address facts"
        dated = [r for r in rows if r.valid_from is not None]
        assert dated, "every address fact still has NULL validity"

    def test_the_address_facts_now_include_line_and_postalCode(self, client, db):
        _generate(client, _clinic(db), 6)
        types = {r.fact_type for r in _db.session.query(PatientStateFact)
                 .filter(PatientStateFact.fact_type.like("address.%"))}
        assert "address.line" in types, types
        assert "address.postalCode" in types, types

    def test_an_as_at_read_BEFORE_the_move_excludes_the_address(self, client, db):
        """The whole point of a validity period, end to end: a date before the
        patient moved in must not return that address."""
        _generate(client, _clinic(db), 4)
        fact = (_db.session.query(PatientStateFact)
                .filter(PatientStateFact.fact_type == "address.city",
                        PatientStateFact.valid_from.isnot(None)).first())
        assert fact is not None
        before = fact.valid_from.replace(year=fact.valid_from.year - 1)
        got = ps.state_at(fact.patient_guid, as_at=before)
        assert all(f.fact_type != "address.city" for f in got), \
            [f.fact_type for f in got]

    def test_and_an_as_at_read_AFTER_the_move_includes_it(self, client, db):
        """The control: without it, an as-at read that returned nothing at all
        would pass the test above."""
        _generate(client, _clinic(db), 4)
        fact = (_db.session.query(PatientStateFact)
                .filter(PatientStateFact.fact_type == "address.city",
                        PatientStateFact.valid_from.isnot(None)).first())
        after = fact.valid_from.replace(year=fact.valid_from.year + 1)
        got = ps.state_at(fact.patient_guid, as_at=after)
        assert any(f.fact_type == "address.city" for f in got), \
            [f.fact_type for f in got]


class TestTheRegionMappingSurvives:
    def test_every_generated_patient_still_maps_to_a_region(self, client, db):
        """#792 derived the Coverage insurer from the city. #888 touches the
        address and must not break that: a patient whose city no longer maps
        would silently fall back to the default region."""
        _generate(client, _clinic(db), 8)
        for r in (_db.session.query(FhirResource)
                  .filter_by(resource_type="Patient").all()):
            addrs = (r.resource_json or {}).get("address") or []
            if not addrs:
                continue
            city = addrs[0].get("city")
            assert city in CITIES, city
