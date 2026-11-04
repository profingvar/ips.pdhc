"""#920 — the provenance tag must be written in the space alert READS.

This module used to write `https://alert.pdhc/provenance`: a host with no
TLD, which resolves nowhere, and a DIFFERENT identifier space from the one
alert's own `inflow/gate.py` reads (`urn:pdhc:provenance`). So a Device
produced here from an alert assertion carried a tag alert's gate would not
recognise — `provenance_of` matches `system` by EQUALITY, would have found
no provenance at all, and would have refused the candidate as
`no_provenance`.

The failure was silent in the useful direction and loud in the useless one:
the push worked, the tag was written, the FHIR looked right, and only a round
trip ever noticed. Which is why the round trip is now a test in BOTH repos.

ALERT OWNS THE VALUE, and it was never ours to choose. Its FROZEN Rule 30
states the MDR boundary in terms of `urn:pdhc:provenance#computed` and says
it "is not configurable"; its design doc uses that space throughout. And the
database agrees overwhelmingly — measured in production 2026-11-04:

    urn:pdhc:provenance            Flag         43
    urn:pdhc:provenance            Observation 104
    https://alert.pdhc/provenance  Device        1
    https://alert.pdhc/provenance  DeviceUsage   1

147 resources were already on the right space. The implant transport was the
only thing on the wrong one, in the same table.

The `#fragment` form in alert's documentation is shorthand for a PAIR: FHIR's
Coding carries `system` and `code` separately, and `gate.provenance_of` reads
`t["system"] == PROVENANCE_SYSTEM` then returns `t["code"]`. So the two
shapes already agreed; only the string did not.
"""
import pytest

from app.services import alert_implants
from app.services.alert_implants import SIMULATED, to_fhir

#: Mirrors `alert.pdhc/app/inflow/gate.py::PROVENANCE_SYSTEM`. Two copies of
#: one fact is normally the thing to avoid — but the two live in different
#: repositories with no import between them, and detecting divergence is this
#: constant's whole job. alert has the twin of this test. A reader can diff
#: them; this suite fails if ours moves.
ALERT_PROVENANCE_SYSTEM = "urn:pdhc:provenance"


def _assertion(**over):
    a = {
        "patient_guid": "00000000-0000-0000-0000-000000000001",
        "subgroup": alert_implants.IMPLANT_SUBGROUP,
        "code_system": "icd10",
        "code": "Z95.0",
        "national_term": "pacemaker",
        "asserted_at": "2026-03-14T09:30:00+00:00",
        "negation": False,
        "provenance": "documented",
    }
    a.update(over)
    return a


class TestTheSystemUri:
    def test_it_is_the_space_alert_reads(self):
        assert alert_implants._PROVENANCE_SYSTEM == ALERT_PROVENANCE_SYSTEM

    def test_it_is_not_the_old_value(self):
        """Named explicitly, because the old one was a plausible-looking URL
        and the next person to need a provenance system will copy whatever
        they find."""
        assert "alert.pdhc/provenance" not in alert_implants._PROVENANCE_SYSTEM
        assert not alert_implants._PROVENANCE_SYSTEM.startswith("http")

    def test_it_names_a_host_that_does_not_have_to_exist(self):
        """A `urn:` is an identifier and is not expected to resolve. The old
        value looked like a URL and named `alert.pdhc`, which has no TLD and
        resolves nowhere — the worst of both: it invited dereferencing and
        could not be dereferenced."""
        assert alert_implants._PROVENANCE_SYSTEM.startswith("urn:")


class TestEveryPathCarriesIt:
    @pytest.mark.parametrize("negation", [False, True],
                             ids=["present", "absent"])
    @pytest.mark.parametrize("provenance", ["documented", SIMULATED])
    def test_both_paths_and_both_provenances(self, negation, provenance):
        """#886 carries the tag on the negated path too, and this test exists
        because a regression there would hide a SIMULATED assertion inside an
        'established absent' record — the MDR-relevant confusion."""
        resources = to_fhir(_assertion(negation=negation,
                                       provenance=provenance),
                            patient_ref="Patient/x",
                            device_id="d", usage_id="u")
        assert resources, "the transform produced nothing"
        for body in resources:
            tags = (body.get("meta") or {}).get("tag") or []
            assert tags, f"{body['resourceType']} carries no meta.tag"
            assert tags[0]["system"] == ALERT_PROVENANCE_SYSTEM
            assert tags[0]["code"] == provenance

    def test_the_code_is_the_BARE_value_not_a_fragment(self):
        """`gate.provenance_of` returns `t["code"]` and compares it against
        alert's `PROVENANCES` tuple, which holds bare values. Writing
        `urn:pdhc:provenance#simulated` into `code` would pass the system
        check and then fail the vocabulary one."""
        resources = to_fhir(_assertion(provenance=SIMULATED),
                            patient_ref="Patient/x",
                            device_id="d", usage_id="u")
        for body in resources:
            code = body["meta"]["tag"][0]["code"]
            assert code == "simulated"
            assert "#" not in code
            assert ":" not in code


class TestTheRoundTripAlertWillDo:
    """alert's `gate.provenance_of` reimplemented here, from its source, so a
    divergence fails in THIS repo too and not only in alert's.

    Copying a function into a test is normally wrong. It is right here for
    the same reason the mirrored constant is: there is no import between the
    two repositories, so the only alternative is for neither side to check.
    """

    @staticmethod
    def _alert_provenance_of(source_resource):
        if not isinstance(source_resource, dict):
            return None
        tags = ((source_resource.get("meta") or {}).get("tag") or [])
        for t in tags:
            if isinstance(t, dict) and t.get("system") == ALERT_PROVENANCE_SYSTEM:
                code = t.get("code")
                if code:
                    return str(code)
        return None

    @pytest.mark.parametrize("provenance", ["documented", SIMULATED])
    def test_alert_can_read_back_what_we_write(self, provenance):
        resources = to_fhir(_assertion(provenance=provenance),
                            patient_ref="Patient/x",
                            device_id="d", usage_id="u")
        for body in resources:
            got = self._alert_provenance_of(body)
            assert got == provenance, (
                f"alert's gate would read {got!r} from a "
                f"{body['resourceType']} we produced — before #920 it read "
                f"None and refused the candidate as no_provenance")

    def test_CONTROL_the_old_system_would_NOT_read_back(self):
        """Without this, the test above would pass for a resolver that
        accepted anything."""
        stale = {"resourceType": "Device",
                 "meta": {"tag": [{"system": "https://alert.pdhc/provenance",
                                   "code": "simulated"}]}}
        assert self._alert_provenance_of(stale) is None
