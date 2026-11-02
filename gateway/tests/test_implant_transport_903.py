"""EPS B6b (#903) — the alert.pdhc implant transport, ips side.

#886 built the transformation and deliberately shipped no transport.
#903 refused to write an HTTP CLIENT against alert.pdhc, because alert
runs nowhere — no container locally or on miserver, no directory under
`/usr/local/www`, no row in CLAUDE.md's service table — and a client
needs a base URL whose module-level default would manufacture a
configured-looking service out of an unset variable. That is the xlate
defect (#833): "nobody wired this up" becomes indistinguishable from "it
blipped", and a permanent condition is reported as retryable.

A RECEIVER has none of that. It names no URL, invents no default, and is
inert until something calls it. So this half is built and proved now, and
whether alert is ever deployed blocks nothing.

The checks below are grouped by the thing that could go wrong rather
than by route, because the interesting failures are all semantic: the
natural key, the negated path, the provenance marker, and the timing
field.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services.alert_implants import IMPLANT_SUBGROUP, SIMULATED
from app.services.auth_service import hash_api_key, SCOPE_IMPLANTS_WRITE

URL = "/api/v1/implants/assertions"
ASSERTED = "2019-04-12"


@pytest.fixture
def patient(client, db):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid,
                     resource_id=str(uuid.uuid4()),
                     family_name="Implantsson", given_name="Test")
    db.session.add(p)
    db.session.commit()
    return p


def _assertion(patient, **over):
    a = {
        "patient_guid": str(patient.guid),
        "subgroup": IMPLANT_SUBGROUP,
        "code_system": "urn:oid:1.2.752.116.1.1.1.1.3",   # ICD-10-SE
        "code": "Z95.0",
        "national_term": "Pacemaker",
        "asserted_at": ASSERTED,
        "negation": False,
        "provenance": "documented",
    }
    a.update(over)
    return a


def _push(client, *rows):
    return client.post(URL, json={"assertions": list(rows)})


def _devices(patient):
    return db_devices(patient, "Device")


def db_devices(patient, rtype):
    return (_db.session.query(FhirResource)
            .filter_by(resource_type=rtype, patient_guid=patient.guid)
            .all())


# =====================================================================
# 1. The scope — #903 step 3, "scoped to the one route and nothing else"
# =====================================================================

class TestItIsScoped:
    def _key(self, db, scopes):
        raw = f"k-{uuid.uuid4()}"
        db.session.add(ApiKey(key_hash=hash_api_key(raw), label="903",
                              prefix=raw[:8], scopes=scopes, is_active=True))
        db.session.commit()
        return raw

    def test_no_credential_is_refused(self, client, db, patient):
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            r = client.post(URL, json={"assertions": []})
        assert r.status_code == 401

    def test_a_key_WITHOUT_the_scope_is_refused(self, client, db, patient):
        raw = self._key(db, ["something:else"])
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            r = client.post(URL, json={"assertions": []},
                            headers={"Authorization": f"ApiKey {raw}"})
        assert r.status_code == 403
        assert SCOPE_IMPLANTS_WRITE in r.get_data(as_text=True)

    def test_a_key_WITH_the_scope_is_admitted(self, client, db, patient):
        raw = self._key(db, [SCOPE_IMPLANTS_WRITE])
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            r = client.post(URL, json={"assertions": [_assertion(patient)]},
                            headers={"Authorization": f"ApiKey {raw}"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["accepted"] == 1

    def test_an_unscoped_legacy_key_cannot_push_implants(
            self, client, db, patient):
        """Every key issued before #903 has scopes=[]. None of them
        reaches this route — which is the narrowing #760 asks for."""
        raw = self._key(db, [])
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            r = client.post(URL, json={"assertions": [_assertion(patient)]},
                            headers={"Authorization": f"ApiKey {raw}"})
        assert r.status_code == 403


# =====================================================================
# 2. The contract — a batch reports, it does not fail whole
# =====================================================================

class TestTheContract:
    def test_a_good_assertion_creates_a_device_and_a_usage(
            self, client, db, patient):
        r = _push(client, _assertion(patient))
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["accepted"] == 1
        assert body["rejected"] == []
        types = sorted(c["resourceType"] for c in body["created"])
        assert types == ["Device", "DeviceUsage"]

    def test_a_missing_field_is_NAMED_not_a_keyerror(
            self, client, db, patient):
        bad = _assertion(patient)
        del bad["national_term"]
        r = _push(client, bad)
        assert r.status_code == 200
        rej = r.get_json()["rejected"]
        assert len(rej) == 1
        assert rej[0]["reason"] == "missing_fields"
        assert "national_term" in rej[0]["missing"]

    def test_one_bad_row_does_NOT_lose_the_good_ones(
            self, client, db, patient):
        """A batch that 400s on one malformed row makes the producer
        retry the rows that already landed."""
        bad = _assertion(patient)
        del bad["asserted_at"]
        good = _assertion(patient, code="Z95.1", national_term="Aortaklaff")
        r = _push(client, bad, good)
        assert r.status_code == 200
        body = r.get_json()
        assert body["accepted"] == 1
        assert len(body["rejected"]) == 1
        assert body["rejected"][0]["index"] == 0

    def test_another_subgroup_is_refused_by_NAME(self, client, db, patient):
        r = _push(client, _assertion(patient, subgroup="Allergi"))
        rej = r.get_json()["rejected"][0]
        assert rej["reason"] == "not_an_implant_subgroup"
        assert rej["subgroup"] == "Allergi"

    def test_an_unknown_patient_is_refused(self, client, db, patient):
        a = _assertion(patient, patient_guid=str(uuid.uuid4()))
        rej = _push(client, a).get_json()["rejected"][0]
        assert rej["reason"] == "unknown_patient"

    def test_a_non_guid_patient_is_refused_not_crashed(
            self, client, db, patient):
        a = _assertion(patient, patient_guid="not-a-guid")
        rej = _push(client, a).get_json()["rejected"][0]
        assert rej["reason"] == "patient_guid_not_a_guid"

    def test_a_row_that_is_not_an_object_is_refused(
            self, client, db, patient):
        r = client.post(URL, json={"assertions": ["a string"]})
        assert r.status_code == 200
        assert r.get_json()["rejected"][0]["reason"] == "not_an_object"

    def test_a_malformed_BODY_is_a_400(self, client, db, patient):
        """A malformed row reports; a malformed body is a real 400."""
        assert client.post(URL, json={"assertions": "nope"}
                           ).status_code == 400
        assert client.post(URL, json={}).status_code == 400

    def test_an_empty_batch_is_accepted_as_a_no_op(self, client, db, patient):
        r = _push(client)
        assert r.status_code == 200
        assert r.get_json() == {"accepted": 0, "duplicates": 0,
                                "rejected": [], "created": []}

    def test_an_oversized_batch_is_refused_with_the_limit(
            self, client, db, patient):
        from app.api.implant_routes import MAX_BATCH
        rows = [_assertion(patient)] * (MAX_BATCH + 1)
        r = client.post(URL, json={"assertions": rows})
        assert r.status_code == 413
        assert r.get_json()["max_batch"] == MAX_BATCH


# =====================================================================
# 3. Idempotence — #903 step 4
# =====================================================================

class TestIdempotence:
    def test_the_same_assertion_pushed_twice_creates_ONE_device(
            self, client, db, patient):
        a = _assertion(patient)
        first = _push(client, a).get_json()
        second = _push(client, a).get_json()
        assert first["accepted"] == 1
        assert second["accepted"] == 0
        assert second["duplicates"] == 1
        assert len(db_devices(patient, "Device")) == 1
        assert len(db_devices(patient, "DeviceUsage")) == 1

    def test_a_re_push_in_the_SAME_batch_is_also_deduplicated(
            self, client, db, patient):
        a = _assertion(patient)
        body = _push(client, a, a).get_json()
        assert body["accepted"] == 1
        assert body["duplicates"] == 1
        assert len(db_devices(patient, "Device")) == 1

    def test_the_same_CODE_with_a_DIFFERENT_national_term_is_DISTINCT(
            self, client, db, patient):
        """The heart of the natural key, and the reason
        (code_system, code) alone is not one: twelve codes in this
        selection bind two or three national terms. Z95.0 covers the
        pacemaker and the pacemaker electrode, and they are not the same
        implant.
        """
        _push(client, _assertion(patient, national_term="Pacemaker"))
        body = _push(client, _assertion(
            patient, national_term="Pacemakerelektrod")).get_json()
        assert body["accepted"] == 1, "the term is not part of the key"
        assert body["duplicates"] == 0
        assert len(db_devices(patient, "Device")) == 2

    def test_a_different_asserted_at_is_a_different_assertion(
            self, client, db, patient):
        _push(client, _assertion(patient))
        body = _push(client, _assertion(
            patient, asserted_at="2021-08-03")).get_json()
        assert body["accepted"] == 1
        assert len(db_devices(patient, "Device")) == 2

    def test_the_same_assertion_for_a_DIFFERENT_patient_is_distinct(
            self, client, db, patient):
        other_fhir = FhirResource(
            resource_type="Patient", resource_id=str(uuid.uuid4()),
            resource_json={"resourceType": "Patient"})
        db.session.add(other_fhir)
        db.session.flush()
        other = PatientIndex(fhir_resource_guid=other_fhir.guid,
                             resource_id=str(uuid.uuid4()),
                             family_name="Annan", given_name="Test")
        db.session.add(other)
        db.session.commit()

        _push(client, _assertion(patient))
        body = _push(client, _assertion(other)).get_json()
        assert body["accepted"] == 1
        assert len(db_devices(patient, "Device")) == 1
        assert len(db_devices(other, "Device")) == 1

    def test_the_derived_ids_are_stable_across_calls(self):
        """They are a UUIDv5 of the natural key, so they must not depend
        on anything else — a random component would break idempotence
        silently on the second push."""
        from app.api.implant_routes import _derived_ids
        a = {"patient_guid": "p", "code_system": "s", "code": "c",
             "national_term": "t", "asserted_at": "2020-01-01"}
        assert _derived_ids(a) == _derived_ids(dict(a))

    def test_the_device_and_usage_ids_differ(self):
        from app.api.implant_routes import _derived_ids
        d, u = _derived_ids({"patient_guid": "p", "code_system": "s",
                             "code": "c", "national_term": "t",
                             "asserted_at": "x"})
        assert d != u


# =====================================================================
# 4. The three cautions carried from #886
# =====================================================================

class TestTheCautions:
    def test_a_SIMULATED_assertion_stays_marked_in_the_resource(
            self, client, db, patient):
        """The MDR-relevant one: a simulated alert that cannot be told
        from a real one is the defect euips_sections' own alerts note
        warns about."""
        _push(client, _assertion(patient, provenance=SIMULATED))
        dev = db_devices(patient, "Device")[0]
        tags = dev.resource_json["meta"]["tag"]
        assert any(t["code"] == SIMULATED for t in tags)
        assert any("SIMULATED" in t["display"] for t in tags)

    def test_a_documented_assertion_is_marked_differently(
            self, client, db, patient):
        _push(client, _assertion(patient, provenance="documented"))
        dev = db_devices(patient, "Device")[0]
        tags = dev.resource_json["meta"]["tag"]
        assert any(t["code"] == "documented" for t in tags)
        assert not any("SIMULATED" in t.get("display", "") for t in tags)

    def test_the_usage_is_timed_by_asserted_at_NOT_by_now(
            self, client, db, patient):
        """recorded_at would date every implant to the day it was
        imported."""
        _push(client, _assertion(patient))
        usage = db_devices(patient, "DeviceUsage")[0]
        assert usage.resource_json["timingDateTime"] == ASSERTED

    def test_the_national_term_lands_in_codeableconcept_TEXT(
            self, client, db, patient):
        """FHIR defines `text` as the representation the user selected,
        which is what a national term is — and the code alone cannot
        carry it."""
        _push(client, _assertion(patient, national_term="Aortaklaff"))
        dev = db_devices(patient, "Device")[0]
        assert dev.resource_json["type"]["text"] == "Aortaklaff"

    def test_this_module_carries_no_copy_of_the_specification(self):
        """The Socialstyrelsen selection is copyright-protected. Codes
        come from alert's own rows; a table of them here would be a
        reproduction."""
        import inspect
        from app.api import implant_routes
        src = inspect.getsource(implant_routes)
        # No code literals from the selection, and no term list.
        assert "Z95" not in src
        assert "Pacemaker" not in src


class TestNegation:
    def test_a_negated_assertion_creates_ONE_device_and_no_usage(
            self, client, db, patient):
        """Established ABSENT uses the section's own absent code, not a
        Device with a flag — a Device would make every consumer see an
        implant that is not there. And no DeviceUsage, because nothing
        is in use."""
        body = _push(client, _assertion(patient, negation=True)).get_json()
        assert body["accepted"] == 1
        assert len(db_devices(patient, "Device")) == 1
        assert db_devices(patient, "DeviceUsage") == []

    def test_the_negated_device_carries_the_absent_coding(
            self, client, db, patient):
        from app.services import euips_sections as euips
        _push(client, _assertion(patient, negation=True))
        dev = db_devices(patient, "Device")[0]
        assert dev.resource_json["type"] == euips.absent_coding("devices")
        assert dev.resource_json["status"] == "unknown"

    def test_a_negated_assertion_is_also_idempotent(
            self, client, db, patient):
        a = _assertion(patient, negation=True)
        _push(client, a)
        assert _push(client, a).get_json()["duplicates"] == 1
        assert len(db_devices(patient, "Device")) == 1

    def test_the_simulated_marker_survives_the_negated_path_too(
            self, client, db, patient):
        _push(client, _assertion(patient, negation=True,
                                 provenance=SIMULATED))
        dev = db_devices(patient, "Device")[0]
        assert any(t["code"] == SIMULATED
                   for t in dev.resource_json["meta"]["tag"])


# =====================================================================
# 5. Audit
# =====================================================================

class TestAudit:
    def test_a_push_is_audited_with_its_counts(self, client, db, patient):
        bad = _assertion(patient)
        del bad["code"]
        _push(client, _assertion(patient), bad)
        rows = AuditLog.query.filter_by(
            event_type="implant_assertions_push").all()
        assert len(rows) == 1
        d = rows[0].detail
        assert d["received"] == 2
        assert d["accepted"] == 1
        assert d["rejected"] == 1
        assert d["mechanism"] == "alert_implant_transport"

    def test_the_audit_names_the_KEY_that_pushed(self, client, db, patient):
        """So a bad batch can be traced to a credential rather than to
        'some service'."""
        raw = f"k-{uuid.uuid4()}"
        key = ApiKey(key_hash=hash_api_key(raw), label="alert",
                     prefix=raw[:8], scopes=[SCOPE_IMPLANTS_WRITE],
                     is_active=True)
        db.session.add(key)
        db.session.commit()
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            client.post(URL, json={"assertions": [_assertion(patient)]},
                        headers={"Authorization": f"ApiKey {raw}"})
        rows = AuditLog.query.filter_by(
            event_type="implant_assertions_push").all()
        assert rows[0].detail["api_key_prefix"] == key.prefix
