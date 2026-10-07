"""#789 — Swedish personnummer construction and validation.

The generator built every identifier with one line that was wrong twice
(`admin.py:743`):

    personnummer = f"19{mp['birth'].replace('-', '')}-{random.randint(1000, 9999)}"

`mp['birth']` is already `YYYY-MM-DD`, so the "19" doubled the century, and the
last digit is a Luhn checksum rather than a free number.

Measured on 60 live rows before the fix: 60/60 the wrong length, the check
digit valid in 6/60 — exactly chance. Four of 60 were self-contradictory: a
2000s birth became `19` + `20xx`, so the identifier claimed a 1920s birth while
the row's own `birth_date` disagreed.

The last of those is the one a length check and a checksum both miss, so it has
its own test. An identifier that is internally well-formed and disagrees with
the record it sits on is worse than a malformed one, because every validator
passes it.
"""
from __future__ import annotations

import random
from datetime import date

import pytest

from app.services import personnummer as pnr


class TestLuhnCheckDigit:
    def test_a_known_value(self):
        # 811218-9876 is the canonical example used in Swedish documentation.
        assert pnr.luhn_check_digit("811218987") == 6

    def test_it_refuses_the_wrong_length(self):
        """Passing 10 digits would silently check the wrong thing."""
        with pytest.raises(ValueError):
            pnr.luhn_check_digit("8112189876")
        with pytest.raises(ValueError):
            pnr.luhn_check_digit("81121898")

    def test_it_refuses_non_digits(self):
        with pytest.raises(ValueError):
            pnr.luhn_check_digit("81121898x")


class TestBuild:
    def test_the_century_is_not_doubled(self):
        """THE bug. The birth date already carries the century."""
        p = pnr.build("1961-10-15")
        assert p.startswith("19611015-"), p
        assert not p.startswith("1919"), f"century doubled again: {p}"
        assert len(p) == 13, f"{p} is {len(p)} chars, expected 13"

    def test_a_2000s_birth_does_not_become_1920(self):
        """The worst variant: four live rows claim a 1920s birth for a patient
        born in the 2000s, contradicting their own birth_date."""
        p = pnr.build("2005-11-05")
        assert p.startswith("20051105-"), p
        assert not p.startswith("1920"), f"still mangled: {p}"

    def test_the_check_digit_is_computed_not_random(self):
        """1000 identifiers, every one valid. Before the fix this was ~10%."""
        rng = random.Random(1234)
        built = [pnr.build(date(rng.randint(1930, 2015), rng.randint(1, 12),
                               rng.randint(1, 28)), rng=rng)
                 for _ in range(1000)]
        invalid = [p for p in built if not pnr.is_valid(p)]
        assert invalid == [], f"{len(invalid)} of 1000 invalid, e.g. {invalid[:3]}"

    def test_it_agrees_with_the_birth_date_it_was_built_from(self):
        rng = random.Random(7)
        for _ in range(200):
            b = date(rng.randint(1930, 2015), rng.randint(1, 12), rng.randint(1, 28))
            assert pnr.is_valid(pnr.build(b, rng=rng), birth=b)

    def test_a_four_digit_serial_is_refused_not_truncated(self):
        """Truncating would drop the caller's digit and silently substitute a
        computed one -- which is how a wrong check digit would come back."""
        with pytest.raises(ValueError):
            pnr.build("1961-10-15", serial=9876)

    def test_a_malformed_birth_is_refused(self):
        with pytest.raises(ValueError):
            pnr.build("15/10/1961")


class TestNormalise:
    @pytest.mark.parametrize("raw,expected", [
        ("19611015-9638", "19611015-9638"),
        ("196110159638", "19611015-9638"),
        ("6110159638", "19611015-9638"),
    ])
    def test_accepted_forms(self, raw, expected):
        assert pnr.normalise(raw) == expected

    def test_the_short_form_infers_a_sensible_century(self):
        """A 2-digit year must not resolve to a future date."""
        n = pnr.normalise("050101-0000")
        assert n is not None
        assert int(n[:4]) <= date.today().year

    def test_the_plus_form_means_over_a_hundred(self):
        a = pnr.normalise("200101-0000")
        b = pnr.normalise("200101+0000")
        assert a and b and int(b[:4]) == int(a[:4]) - 100

    @pytest.mark.parametrize("junk", ["", "abc", "1234", "19611015_9638", None])
    def test_junk_is_rejected_rather_than_coerced(self, junk):
        assert pnr.normalise(junk) is None


class TestIsValid:
    def test_the_actual_live_value_fails(self):
        """`1919611015-9638` is a real value from the database."""
        assert pnr.is_valid("1919611015-9638") is False

    def test_an_impossible_date_fails(self):
        p = pnr.build("1961-01-15")
        broken = "19610231-" + p[9:]
        assert pnr.is_valid(broken) is False

    def test_a_wrong_check_digit_fails(self):
        p = pnr.build("1961-10-15")
        wrong = p[:-1] + str((int(p[-1]) + 1) % 10)
        assert pnr.is_valid(wrong) is False

    def test_a_well_formed_identifier_that_contradicts_the_record_fails(self):
        """The failure mode no length or checksum test catches.

        This identifier is internally perfect; it simply belongs to a
        different person's birth date. Four live rows are in this state.
        """
        p = pnr.build("1961-10-15")
        assert pnr.is_valid(p) is True
        assert pnr.is_valid(p, birth="1985-03-02") is False


class TestDescribeInvalid:
    def test_it_names_the_check_digit_and_what_it_should_be(self):
        p = pnr.build("1961-10-15")
        wrong = p[:-1] + str((int(p[-1]) + 1) % 10)
        msg = pnr.describe_invalid(wrong)
        assert msg and "check digit" in msg and "Luhn" in msg

    def test_it_names_the_disagreement_with_the_record(self):
        p = pnr.build("1961-10-15")
        msg = pnr.describe_invalid(p, birth="1985-03-02")
        assert msg and "1961-10-15" in msg and "1985-03-02" in msg

    def test_a_valid_value_has_nothing_to_describe(self):
        assert pnr.describe_invalid(pnr.build("1961-10-15")) is None

    def test_it_does_not_crash_on_junk(self):
        """This runs on the warning path of two live endpoints, so a crash here
        would only ever fire when something was ALREADY wrong."""
        for junk in ("", "   ", "abc", "1234", "19611015_9638"):
            assert isinstance(pnr.describe_invalid(junk), str)
