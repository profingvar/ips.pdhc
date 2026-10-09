"""One definition of "is this a UUID", for every route that filters on one.

## Why this module exists

Several of ips's columns are real UUID types (`GUID()`): `patient_index.guid`,
`clinics.guid`, and others. Handing a UUID column a value that is not a UUID
does not return no rows — it RAISES at the driver, and Flask turns that into a
**500**. The route's own `404 not found` branch is then unreachable for exactly
the inputs it was written for.

That has now been three separate incidents:

* **#730** — `analysis_filter` answered 500 for a cohort containing one
  malformed guid. cdr turned the 500 into `IpsUnreachable` and fail-closed the
  whole read, reporting a sibling outage. One bad guid denied an entire cohort
  and blamed the wrong service.
* **#791** — the euIPS section route needed the same check, so the helper was
  hoisted out of `analysis_filter` rather than copied. Its docstring records
  why: "a second copy would be two definitions of one rule, and the shape that
  cost #784 and #786 a day each."
* **#805** — all four `clinics/<guid>` routes still had it. Found when
  request.pdhc's new patient list probed an unknown clinic and got a 500 where
  a 404 was meant.

So it lives here now, imported by both API modules, rather than in one of them
and borrowed by the other.

## What a caller should do with it

Return **400** for a malformed identifier, not 404. They are different
answers: 404 says "that thing does not exist", 400 says "that is not an
identifier". A consumer cannot tell a 500 from "the service is down" — which is
precisely how #730 became a reported outage — and cannot tell a 404 from "my
input was rubbish".
"""
import uuid


def is_uuid(value) -> bool:
    """True when `value` parses as a UUID.

    Deliberately total: any unparseable input is False rather than an
    exception, because every caller is guarding a query and wants a verdict.
    """
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False
