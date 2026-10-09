"""#811 — the ips generator takes an AGE RANGE.

Operator: "Set the age range in the IPS generator." The generator previously
hardcoded `random.randint(1940, 2010)` birth years, so every cohort spanned the
same 70 years and a plandef aimed at, say, a 40-75 population could not be
given a matching patient set.

Two things these tests are really about:

* **Ages, not birth years.** Converting in your head is annoying and drifts a
  year every January. The form and the service both take ages.
* **The off-by-one.** Sampling a birth *year* gives an age that is one too low
  for everyone whose birthday has not happened yet this year — which is most of
  a cohort for most of the year. Asked for 40-75, the operator must not get
  39-year-olds. `_birth_date_for_age` computes from the age instead, and
  `test_no_patient_is_a_year_young` is the test that would catch a regression
  to year-sampling.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services import mock_generator as mg


def _age_on(birth_iso: str, today: date) -> int:
    b = date.fromisoformat(birth_iso)
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


# ---------------------------------------------------------------------------
# resolve_age_range
# ---------------------------------------------------------------------------

def test_blank_means_the_default_span():
    """Leaving the fields empty must behave as the generator always did."""
    assert mg.resolve_age_range(None, None) == (mg.DEFAULT_AGE_MIN,
                                                mg.DEFAULT_AGE_MAX)
    assert mg.resolve_age_range("", "") == (mg.DEFAULT_AGE_MIN,
                                            mg.DEFAULT_AGE_MAX)


def test_one_bound_given_keeps_the_default_for_the_other():
    lo, hi = mg.resolve_age_range(40, None)
    assert (lo, hi) == (40, mg.DEFAULT_AGE_MAX)
    lo, hi = mg.resolve_age_range(None, 75)
    assert (lo, hi) == (mg.DEFAULT_AGE_MIN, 75)


def test_strings_from_a_form_are_accepted():
    assert mg.resolve_age_range("40", "75") == (40, 75)


def test_an_INVERTED_range_is_REFUSED_not_silently_swapped():
    """Swapping them would be friendly and wrong: the operator asked for
    something impossible and should be told, not guessed at."""
    with pytest.raises(mg.AgeRangeError):
        mg.resolve_age_range(75, 40)


@pytest.mark.parametrize("lo,hi", [(-1, 50), (10, 200), (-5, -1)])
def test_a_range_outside_the_sanity_bounds_is_REFUSED(lo, hi):
    with pytest.raises(mg.AgeRangeError):
        mg.resolve_age_range(lo, hi)


def test_a_single_age_is_a_valid_range():
    assert mg.resolve_age_range(50, 50) == (50, 50)


# ---------------------------------------------------------------------------
# The birth dates the pool actually produces
# ---------------------------------------------------------------------------

def test_every_patient_is_INSIDE_the_requested_range():
    today = date.today()
    pool = mg._build_unique_patient_pool(60, age_min=40, age_max=75)
    assert len(pool) == 60
    ages = [_age_on(p["birth"], today) for p in pool]
    assert min(ages) >= 40, f"someone is {min(ages)}, below the requested 40"
    assert max(ages) <= 75, f"someone is {max(ages)}, above the requested 75"


def test_no_patient_is_a_year_YOUNG():
    """The regression guard for year-sampling.

    `year = today.year - age` alone makes everyone whose birthday falls later
    in the calendar year one year younger than asked for. Requesting a single
    age makes that off-by-one unmissable: all 40 must be exactly 50.
    """
    today = date.today()
    pool = mg._build_unique_patient_pool(40, age_min=50, age_max=50)
    ages = {_age_on(p["birth"], today) for p in pool}
    assert ages == {50}, f"expected every patient to be 50, got {sorted(ages)}"


def test_a_single_age_holds_for_EVERY_day_of_the_year():
    """Not just today. The conversion has to be correct on 1 January and on
    31 December, which a test run only in October would not reveal.
    """
    import random
    for probe in (date(2026, 1, 1), date(2026, 6, 30), date(2026, 12, 31)):
        for _ in range(40):
            birth = mg._birth_date_for_age(50, random, today=probe)
            assert _age_on(birth, probe) == 50, (
                f"age {_age_on(birth, probe)} != 50 on {probe} "
                f"for birth {birth}")


def test_every_birth_date_is_a_REAL_date():
    """Day is capped at 28 so no month/day pair can be invalid and 29
    February never has to be reasoned about."""
    pool = mg._build_unique_patient_pool(80, age_min=0, age_max=100)
    for p in pool:
        d = date.fromisoformat(p["birth"])   # raises on an impossible date
        assert d.day <= 28


def test_a_narrow_ADULT_range_produces_no_minors():
    """The guardian logic keys off being a minor. An adult-only cohort must
    therefore produce no guardians, and that follows from the birth dates
    rather than from a separate switch."""
    today = date.today()
    pool = mg._build_unique_patient_pool(50, age_min=40, age_max=75)
    assert all(_age_on(p["birth"], today) >= 18 for p in pool)


def test_a_CHILD_range_produces_only_minors():
    today = date.today()
    pool = mg._build_unique_patient_pool(30, age_min=2, age_max=15)
    ages = [_age_on(p["birth"], today) for p in pool]
    assert max(ages) <= 15
    assert all(a < 18 for a in ages)


def test_the_default_span_still_spans_broadly():
    """A cohort with no range given must not collapse to one age."""
    today = date.today()
    pool = mg._build_unique_patient_pool(120)
    ages = [_age_on(p["birth"], today) for p in pool]
    assert max(ages) - min(ages) > 20, (
        "the default range no longer produces a mixed-age cohort")
    assert min(ages) >= mg.DEFAULT_AGE_MIN
    assert max(ages) <= mg.DEFAULT_AGE_MAX


def test_patients_stay_unique_within_a_narrow_range():
    """The name pool is combinatorial and independent of age; narrowing the
    ages must not start producing duplicate people."""
    pool = mg._build_unique_patient_pool(100, age_min=50, age_max=51)
    assert len({(p["family"], p["given"]) for p in pool}) == 100


# ---------------------------------------------------------------------------
# Through the admin form
# ---------------------------------------------------------------------------

def test_the_form_rejects_a_bad_range_WITHOUT_creating_anyone(client, db):
    """"No patients were created" has to be true, not just reassuring."""
    from app.models.clinic import Clinic
    from app.models.patient_index import PatientIndex
    import uuid as _uuid

    clinic = Clinic(name="Age Clinic", organisation_guid=str(_uuid.uuid4()))
    db.session.add(clinic)
    db.session.commit()
    before = db.session.query(PatientIndex).count()

    r = client.post("/admin/mock-data", data={
        "clinic_guid": str(clinic.guid), "count": "3",
        "age_min": "75", "age_max": "40", "skip_clinical": "on",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "Age range rejected" in r.get_data(as_text=True)
    assert db.session.query(PatientIndex).count() == before


def test_the_form_generates_within_the_given_range(client, db):
    from app.models.clinic import Clinic
    from app.models.patient_index import PatientIndex
    import uuid as _uuid

    clinic = Clinic(name="Age Clinic 2", organisation_guid=str(_uuid.uuid4()))
    db.session.add(clinic)
    db.session.commit()

    r = client.post("/admin/mock-data", data={
        "clinic_guid": str(clinic.guid), "count": "8",
        "age_min": "40", "age_max": "45", "skip_clinical": "on",
    }, follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "ages 40" in body and "45" in body, (
        "the confirmation does not state the age span actually used")

    today = date.today()
    made = (db.session.query(PatientIndex)
            .filter(PatientIndex.birth_date.isnot(None)).all())
    ages = [_age_on(p.birth_date.isoformat(), today) for p in made]
    assert ages, "no patients were created"
    assert min(ages) >= 40 and max(ages) <= 45, sorted(ages)
