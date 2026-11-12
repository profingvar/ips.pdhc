"""#990 — synthetic personnummer carry a WRONG check digit (#405).

#789 made the generator mint valid real-world numbers (real birth date, random
birth number, correct Luhn digit). 185 of 314 in production on 2026-11-12.
"""
from __future__ import annotations

import random

import pytest

from app.services import personnummer as pnr


@pytest.mark.parametrize("birth", ["1961-01-15", "2004-02-29", "1999-12-31", "1930-07-01"])
def test_build_synthetic_is_well_formed_dated_and_NEVER_valid(birth):
    rng = random.Random(1)
    for _ in range(300):
        v = pnr.build_synthetic(birth, rng=rng)
        assert len(v) == 13
        assert pnr.classify(v) == "synthetic"
        assert pnr.is_valid(v) is False
        assert v[:8] == birth.replace("-", "")


def test_every_serial_on_a_date_gives_a_synthetic_number():
    """Exhaustive over all 1000 birth numbers: none slips through as valid."""
    assert {pnr.classify(pnr.build_synthetic("1961-01-15", s)) for s in range(1000)} == {"synthetic"}


def test_the_synthetic_digit_is_the_correct_one_plus_5():
    v, s = pnr.build("1961-01-15", 123), pnr.build_synthetic("1961-01-15", 123)
    assert v[:-1] == s[:-1] and int(s[-1]) == (int(v[-1]) + 5) % 10


def test_classify():
    assert pnr.classify(pnr.build("1961-01-15", 1)) == "real_format"
    assert pnr.classify(pnr.build_synthetic("1961-01-15", 1)) == "synthetic"
    for bad in ("", None, "19611015-963", "1919611015-9638", "19610231-1234", "abc"):
        assert pnr.classify(bad) == "malformed", bad


def test_the_POLICY_warns_on_a_real_format_number_and_accepts_a_synthetic_one():
    real, synth = pnr.build("1961-01-15", 7), pnr.build_synthetic("1961-01-15", 7)
    assert "may be a real person" in pnr.policy_problem(real)
    assert pnr.policy_problem(synth) is None
    assert pnr.policy_problem(synth, birth="1961-01-15") is None


def test_the_policy_still_catches_a_birth_date_contradiction():
    synth = pnr.build_synthetic("1961-01-15", 7)
    assert "encodes a birth date" in pnr.policy_problem(synth, birth="1972-02-03")


def test_the_policy_still_reports_malformed():
    assert pnr.policy_problem("1919611015-9638") is not None


def test_validate_identifier_reports_kind_and_policy(client, db):
    real, synth = pnr.build("1961-01-15", 7), pnr.build_synthetic("1961-01-15", 7)
    r = client.post("/api/v1/patients/validate-identifier",
                    json={"identifiers": [real, synth]}).get_json()["results"]
    assert [x["kind"] for x in r] == ["real_format", "synthetic"]
    assert r[0]["policy_problem"] and r[1]["policy_problem"] is None
