"""Swedish personnummer — construction and validation, in ONE place (#789).

Before this there was no shared definition, and the only code that built one
got it wrong twice in a single line (`admin.py:743`):

    personnummer = f"19{mp['birth'].replace('-', '')}-{random.randint(1000, 9999)}"

`mp['birth']` is already `YYYY-MM-DD`, so `.replace('-','')` yields `19611015`
— the century is there. Prefixing "19" doubled it, giving `1919611015-9638`:
15 characters where `YYYYMMDD-NNNN` is 13. Measured on 60 live rows, 60 were
the wrong length. And the final digit is a Luhn checksum, not a free number, so
`randint(1000, 9999)` made it valid in 6 of 60 — exactly chance.

Worse than merely wrong: a patient born in the 2000s became `19` + `20xx…`, so
the identifier claimed a 1920s birth while the row's own `birth_date` said
otherwise. Four of 60 sampled were in that state.

Three paths in this service mint or accept a personnummer — the mock generator,
the admin create form and `POST /api/v1/clinics/<guid>/patients`. They each had
their own handling, which is how the duplication in #784 (sso's CSV contract)
and #786 (plan's canonical-lib default) started. One definition, three callers.

SYNTHETIC NUMBERS CARRY A WRONG CHECK DIGIT — ON PURPOSE (#405, restored by #990).
#789 made `build()` compute a CORRECT check digit and treated the old invalid
ones as a defect. That turned every generated number into a well-formed,
real-world personnummer: a real birth date, a random birth number, a correct
digit. For an ordinary birth date most of the 1000 birth numbers are issued to
real people, so the generator was minting numbers that can identify a living
person and storing them next to fabricated clinical data (185 of 314 in
production on 2026-11-12). A Skatteverket TEST number would be valid and safe,
but those are a published list; a random serial is not one of them.

So there are now two builders and one classification:
  build()            a structurally VALID number — kept for validating input
                     and for tests of the validator. NEVER for synthetic data.
  build_synthetic()  well-formed, real date, agrees with the birth date, and a
                     check digit that is guaranteed WRONG: it cannot be anyone.
  classify()         "real_format" | "synthetic" | "malformed"
and the platform policy, `SYNTHETIC_ONLY`, under which a real-format number on
input is the thing to warn about — not a synthetic one.

A personnummer is an IDENTIFIER and never a join key. `PatientIndex.guid` is
the internal key across all nine consuming services (Rule 18).
"""
from __future__ import annotations

import random
import re
from datetime import date

# Swedish personal identity number, the HSA/Inera OID. Already the system in
# use for 140 of the 150 live patients.
PERSONNUMMER_SYSTEM = "urn:oid:1.2.752.129.2.1.3.1"

# `YYYYMMDD-NNNN` (13) is what this service stores. `YYMMDD-NNNN` (11) and the
# plus form for people over 100 are accepted on input and normalised, because
# an operator typing one by hand will use the short form.
_FULL = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{4})$")
_SHORT = re.compile(r"^(\d{2})(\d{2})(\d{2})([-+])(\d{4})$")


def luhn_check_digit(nine_digits: str) -> int:
    """The check digit for `YYMMDDNNN` — the Luhn algorithm over 9 digits.

    This is the piece the generator replaced with a random number, so it is
    the whole reason 90% of the live identifiers fail validation.
    """
    if len(nine_digits) != 9 or not nine_digits.isdigit():
        raise ValueError(f"expected 9 digits, got {nine_digits!r}")
    total = 0
    for i, ch in enumerate(nine_digits):
        # Every other digit doubled, starting with the first.
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10


def build(birth: date | str, serial: int | None = None,
          *, rng: random.Random | None = None) -> str:
    """A well-formed `YYYYMMDD-NNNN` for this birth date.

    `serial` is the 3-digit birth number; the 4th digit is COMPUTED. Passing a
    4-digit value is rejected rather than truncated, because silently dropping
    the caller's last digit is how a wrong check digit would come back.
    """
    if isinstance(birth, str):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", birth.strip())
        if not m:
            raise ValueError(f"birth must be YYYY-MM-DD, got {birth!r}")
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
    else:
        yyyy, mm, dd = f"{birth.year:04d}", f"{birth.month:02d}", f"{birth.day:02d}"

    if serial is None:
        r = rng or random
        serial = r.randint(0, 999)
    if not 0 <= serial <= 999:
        raise ValueError(
            f"serial must be the 3-digit birth number 0-999, got {serial!r}. "
            "The 4th digit is the Luhn check digit and is computed here."
        )

    nine = f"{yyyy[2:]}{mm}{dd}{serial:03d}"
    return f"{yyyy}{mm}{dd}-{serial:03d}{luhn_check_digit(nine)}"


def build_synthetic(birth: date | str, serial: int | None = None,
                    *, rng: random.Random | None = None) -> str:
    """A SYNTHETIC `YYYYMMDD-NNNN`: well-formed, the birth date it claims, and
    a check digit that is deliberately WRONG, so it can never be a real
    person's number (#405, #990).

    The wrong digit is the correct one plus 5 (mod 10) — never equal to it,
    and deterministic, so a test can assert it.
    """
    valid = build(birth, serial, rng=rng)
    correct = int(valid[-1])
    return valid[:-1] + str((correct + 5) % 10)


def classify(value: str | None) -> str:
    """"real_format", "synthetic" or "malformed".

    real_format  a well-formed number with a real date and a CORRECT check
                 digit — it can be a real person's.
    synthetic    well-formed, a real date, and a WRONG check digit (#405).
    malformed    anything else (wrong shape, impossible date, empty).
    """
    n = normalise(value or "")
    if n is None:
        return "malformed"
    m = _FULL.match(n)
    if not m:
        return "malformed"
    yyyy, mm, dd, nnnn = m.groups()
    try:
        date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return "malformed"
    correct = luhn_check_digit(f"{yyyy[2:]}{mm}{dd}{nnnn[:3]}") == int(nnnn[3])
    return "real_format" if correct else "synthetic"


#: The platform holds SYNTHETIC data only. Under this policy a real-format
#: number on input is warned about by name. Only the operator changes this,
#: and only when the platform is cleared to hold real patients.
SYNTHETIC_ONLY = "synthetic_only"


def policy_problem(value: str | None, *, birth: date | str | None = None,
                   policy: str = SYNTHETIC_ONLY) -> str | None:
    """What is wrong with `value` UNDER THE PLATFORM POLICY, or None.

    Under SYNTHETIC_ONLY: a real-format number is the problem (it may be a real
    person's); a synthetic one is correct; a malformed one, or one whose date
    contradicts the record, is reported as before.
    """
    kind = classify(value)
    if kind == "malformed":
        return describe_invalid(value or "", birth=birth)
    if birth is not None:
        # Compared directly: describe_invalid reports a wrong check digit
        # FIRST, so for a synthetic number it never reaches the date.
        b = birth
        if isinstance(b, str):
            bm = re.match(r"^(\d{4})-(\d{2})-(\d{2})", b.strip())
            b = date(int(bm.group(1)), int(bm.group(2)), int(bm.group(3))) if bm else None
        n = normalise(value)
        yyyy, mm, dd = n[:4], n[4:6], n[6:8]
        encoded = date(int(yyyy), int(mm), int(dd))
        if b is not None and encoded != b:
            return (f"{n} encodes a birth date of {encoded.isoformat()} but the "
                    f"patient record says {b.isoformat()}")
    if policy == SYNTHETIC_ONLY and kind == "real_format":
        return (f"{normalise(value)} has a CORRECT check digit, so it may be a "
                f"real person's personnummer. This platform holds synthetic "
                f"data only (#405, #990): use a number with a wrong check digit.")
    return None


def normalise(value: str) -> str | None:
    """`YYYYMMDD-NNNN`, or None if the input is not a personnummer at all.

    Accepts the 12-digit and 10-digit forms without a separator too, since
    those arrive from external systems. The short form's century is inferred:
    `+` means the person has turned 100.
    """
    if not value:
        return None
    v = value.strip().replace(" ", "")
    if re.fullmatch(r"\d{12}", v):
        v = f"{v[:8]}-{v[8:]}"
    elif re.fullmatch(r"\d{10}", v):
        v = f"{v[:6]}-{v[6:]}"

    m = _FULL.match(v)
    if m:
        return v
    m = _SHORT.match(v)
    if not m:
        return None
    yy, mm, dd, sep, nnnn = m.groups()
    today = date.today()
    century = today.year // 100 * 100
    year = century + int(yy)
    if year > today.year:
        year -= 100
    if sep == "+":
        year -= 100
    return f"{year:04d}{mm}{dd}-{nnnn}"


def is_valid(value: str, *, birth: date | str | None = None) -> bool:
    """True when `value` is a structurally valid personnummer.

    Checks the date is real and the check digit computes. With `birth` given,
    also checks the identifier AGREES with it — which is the specific failure
    that made four of the sampled rows self-contradictory, and which neither a
    length check nor a checksum alone would catch.
    """
    n = normalise(value)
    if n is None:
        return False
    m = _FULL.match(n)
    if not m:
        return False
    yyyy, mm, dd, nnnn = m.groups()
    try:
        d = date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return False                      # e.g. 31 February
    if luhn_check_digit(f"{yyyy[2:]}{mm}{dd}{nnnn[:3]}") != int(nnnn[3]):
        return False
    if birth is not None:
        b = birth
        if isinstance(b, str):
            bm = re.match(r"^(\d{4})-(\d{2})-(\d{2})", b.strip())
            if not bm:
                return False
            b = date(int(bm.group(1)), int(bm.group(2)), int(bm.group(3)))
        if d != b:
            return False
    return True


def describe_invalid(value: str, *, birth: date | str | None = None) -> str | None:
    """Why `value` is not valid, for a log line or a flash message, or None.

    Separate from is_valid so a caller can report the reason without
    re-deriving it. The messages name the field, because "invalid
    personnummer" sends an operator looking at the wrong thing.
    """
    if not value or not value.strip():
        return "empty"
    n = normalise(value)
    if n is None:
        return (f"{value!r} is not a personnummer: expected YYYYMMDD-NNNN "
                f"or YYMMDD-NNNN")
    m = _FULL.match(n)
    yyyy, mm, dd, nnnn = m.groups()
    try:
        d = date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return f"{n} contains an impossible date ({yyyy}-{mm}-{dd})"
    expected = luhn_check_digit(f"{yyyy[2:]}{mm}{dd}{nnnn[:3]}")
    if expected != int(nnnn[3]):
        return (f"{n} has check digit {nnnn[3]}; the Luhn digit for "
                f"{yyyy[2:]}{mm}{dd}{nnnn[:3]} is {expected}")
    if birth is not None:
        b = birth
        if isinstance(b, str):
            bm = re.match(r"^(\d{4})-(\d{2})-(\d{2})", b.strip())
            b = date(int(bm.group(1)), int(bm.group(2)),
                     int(bm.group(3))) if bm else None
        if b is not None and d != b:
            return (f"{n} encodes a birth date of {d.isoformat()} but the "
                    f"patient record says {b.isoformat()}")
    return None
