"""#813 — ips answers "is this personnummer valid?", because ips owns the rule.

There was no endpoint for it. request.pdhc therefore grew a SECOND Luhn
implementation, that implementation was wrong, and the fix was to delete it
with a note saying ips should be asked instead. This is the endpoint that note
was waiting for.

The deleted check was removed on a false premise, and that is worth recording
where it will be read: it was dropped because it flagged `19610115-9638`, which
I believed ips's generator had produced and considered valid. ips considers it
INVALID — it is a hand-written fixture in `test_euips_header.py`, and the Luhn
check had been right. The lesson is not "trust the local check" but "ask the
service that owns the rule", which is what this is for.
"""
from __future__ import annotations

from app.services import personnummer as pnr

URL = "/api/v1/patients/validate-identifier"


def _post(client, identifiers):
    return client.post(URL, json={"identifiers": identifiers})


def test_a_valid_personnummer_is_valid(client, db):
    good = pnr.build("1961-01-15")
    r = _post(client, [{"value": good, "birth_date": "1961-01-15"}])
    assert r.status_code == 200
    res = r.get_json()["results"][0]
    assert res["valid"] is True
    assert res["problem"] is None
    assert res["normalised"] == good


def test_a_bad_check_digit_is_reported_WITH_the_expected_digit():
    """"invalid personnummer" alone sends an operator looking at the wrong
    thing; the message names the digit it expected."""
    assert pnr.is_valid("19610115-9638") is False
    msg = pnr.describe_invalid("19610115-9638")
    assert "check digit" in msg and "Luhn" in msg


def test_the_two_hand_written_fixtures_are_INVALID(client, db):
    """Pinned deliberately. These are the values that were mistaken for
    generator output, and the mistake deleted a working check in another
    service. If a future change makes them valid, that belief becomes
    plausible again."""
    r = _post(client, ["19610115-9638", "19611015-9638"])
    assert r.status_code == 200
    for res in r.get_json()["results"]:
        assert res["valid"] is False, f"{res['value']} is now considered valid"


def test_the_doubled_century_bug_is_caught(client, db):
    """#789 wrote "19" + "19580314" -> 1919580314-8691."""
    r = _post(client, ["1919580314-8691"])
    res = r.get_json()["results"][0]
    assert res["valid"] is False
    assert "not a personnummer" in res["problem"]


def test_a_VALID_number_that_CONTRADICTS_the_birth_date_is_invalid(client, db):
    """The check that matters most in this data, and the one neither a length
    check nor a checksum alone catches: the identifier is well-formed but
    encodes a different person's birth date from the record."""
    good = pnr.build("1961-01-15")
    r = _post(client, [{"value": good, "birth_date": "1980-05-05"}])
    res = r.get_json()["results"][0]
    assert res["valid"] is False
    assert "encodes a birth date" in res["problem"]
    assert "1961-01-15" in res["problem"] and "1980-05-05" in res["problem"]


def test_a_bare_string_is_accepted_as_well_as_an_object(client, db):
    good = pnr.build("1972-02-03")
    r = _post(client, [good, {"value": good}])
    a, b = r.get_json()["results"]
    assert a["valid"] is True and b["valid"] is True


def test_results_are_IN_ORDER_and_one_per_input(client, db):
    """The caller zips these against its own list, so order and length are
    load-bearing, not cosmetic."""
    good = pnr.build("1961-01-15")
    sent = [good, "19610115-9638", "1919580314-8691"]
    r = _post(client, sent)
    results = r.get_json()["results"]
    assert len(results) == len(sent)
    assert [x["value"] for x in results] == sent
    assert [x["valid"] for x in results] == [True, False, False]


def test_a_MALFORMED_ENTRY_does_not_fail_the_whole_batch(client, db):
    """One bad row must not hide the verdict on every good one."""
    good = pnr.build("1961-01-15")
    r = _post(client, [good, 12345, None, good])
    assert r.status_code == 200
    results = r.get_json()["results"]
    assert len(results) == 4
    assert results[0]["valid"] is True and results[3]["valid"] is True
    assert results[1]["valid"] is False and results[2]["valid"] is False


def test_an_empty_list_is_fine(client, db):
    r = _post(client, [])
    assert r.status_code == 200
    assert r.get_json()["results"] == []


def test_a_missing_or_non_list_body_is_a_400_not_a_500(client, db):
    assert client.post(URL, json={}).status_code == 400
    assert client.post(URL, json={"identifiers": "19610115-9638"}).status_code == 400
    assert client.post(URL, json={"identifiers": {"value": "x"}}).status_code == 400


def test_an_oversized_batch_is_REFUSED(client, db):
    from app.api.patient_routes import MAX_IDENTIFIERS_PER_CALL
    good = pnr.build("1961-01-15")
    r = _post(client, [good] * (MAX_IDENTIFIERS_PER_CALL + 1))
    assert r.status_code == 400
    assert str(MAX_IDENTIFIERS_PER_CALL) in r.get_json()["error"]


def test_it_takes_NO_patient_guid(client, db):
    """A pure function over a value. A caller often holds an identifier
    precisely because it has no patient yet."""
    good = pnr.build("1961-01-15")
    r = _post(client, [good])
    assert r.status_code == 200
    assert r.get_json()["results"][0]["valid"] is True


def test_the_value_is_not_in_the_URL(client, db):
    """POST with the value in the BODY, deliberately: a personnummer is
    personal data, and a URL path reaches the app's access log, nginx's, any
    proxy between, and a Referer header."""
    good = pnr.build("1961-01-15")
    assert client.get(f"{URL}/{good}").status_code in (404, 405)
    assert _post(client, [good]).status_code == 200
