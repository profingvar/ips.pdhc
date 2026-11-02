"""#907 — three element names in the device builders were wrong against R5.

`euips_recommended`'s docstring had listed them as suspected-wrong and
nominated #885 to check. #885 checked them against the published FHIR R5
specification and **all three guesses were correct**, which is what
marking them unverified was for:

  1. `Device.patient` — R5's Device element list has no `patient` at all.
  2. `DeviceUsage.subject` — R5 lists `DeviceUseStatement.subject` as
     *Deleted* and `DeviceUsage.patient` as *Added Mandatory Element*,
     1..1. The right name is also the required one.
  3. The absent coding went into `Device.code`; R5 Device has `type`
     (0..*) and no `code` element.

This service declares `fhirVersion 5.0.0`, so these were defects rather
than a version choice — the same family as #898, which corrected the
resource NAME and did not reach the element names inside it.

THE DECISION #907 HAD TO TAKE FIRST. Removing `Device.patient` removes
the only patient reference inside the Device JSON. In R5 that is not a
loss to work around: it is the standard's own choice, because the
association moved to `DeviceUsage.patient` and `DeviceAssociation`. A
bare R5 Device genuinely cannot say whose it is.

So the linkage is the row's `FhirResource.patient_guid`, which every
write path in this service already passes explicitly — `mock_generator`,
`admin.py:526`, and the implant transport. Only the generic FHIR create
route derived it from the body, and it now also accepts `?patient=`,
checked ONLY when the body supplied nothing so it can never override a
reference the body carries.

THE NEGATED CASE, which #907 said must not be decided by accident:
#886's negated implant path emits a Device with NO DeviceUsage, because
nothing is in use. That Device therefore has no reference anywhere in its
JSON, by design, and its only link is the row. Decided, and in writing.

THE TEST THAT MATTERS MOST is `TestNoUndefinedElements`. #907 said a test
that the emitted Device carries no element R5 does not define "would have
caught all three, and is worth more than three per-element assertions".
It is written against the R5 element list and would have caught them.
"""
from __future__ import annotations

import random
import uuid

import pytest

from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import alert_implants, euips_recommended as rec
from app.services.alert_implants import IMPLANT_SUBGROUP

#: Device's elements in FHIR R5, from hl7.org/fhir/R5/device.html, plus the
#: three elements every resource may carry. `patient` is deliberately NOT
#: here — that absence is the whole point.
R5_DEVICE_ELEMENTS = {
    "resourceType", "id", "meta", "implicitRules", "language", "text",
    "contained", "extension", "modifierExtension",
    "identifier", "displayName", "definition", "udiCarrier", "status",
    "availabilityStatus", "biologicalSourceEvent", "manufacturer",
    "manufactureDate", "expirationDate", "lotNumber", "serialNumber",
    "name", "modelNumber", "partNumber", "category", "type", "version",
    "conformsTo", "property", "mode", "cycle", "duration", "owner",
    "contact", "location", "url", "endpoint", "gateway", "note", "safety",
    "parent",
}

#: DeviceUsage's elements in R5. `subject` is deliberately NOT here.
R5_DEVICEUSAGE_ELEMENTS = {
    "resourceType", "id", "meta", "implicitRules", "language", "text",
    "contained", "extension", "modifierExtension",
    "identifier", "basedOn", "status", "category", "patient", "derivedFrom",
    "context", "timingTiming", "timingPeriod", "timingDateTime",
    "dateAsserted", "usageStatus", "usageReason", "adherence",
    "informationSource", "device", "reason", "bodySite", "note",
}


def _device_pairs():
    """Every Device/DeviceUsage this service builds, from both builders and
    both of the implant paths."""
    out = []
    for seed in range(40):
        out.extend(rec._devices("Patient/x", __import__("datetime").date(
            1960, 1, 1), random.Random(seed)))
    out.append(rec._no_known("devices", "Device", "Patient/x", None,
                             "No known devices."))
    base = {
        "patient_guid": str(uuid.uuid4()), "subgroup": IMPLANT_SUBGROUP,
        "code_system": "urn:oid:1.2.752.116.1.1.1.1.3", "code": "Z95.0",
        "national_term": "Pacemaker", "asserted_at": "2019-04-12",
        "negation": False, "provenance": "documented",
    }
    out.extend(alert_implants.to_fhir(base, patient_ref="Patient/x",
                                      device_id="d", usage_id="u"))
    out.extend(alert_implants.to_fhir({**base, "negation": True},
                                      patient_ref="Patient/x",
                                      device_id="d2"))
    return out


class TestNoUndefinedElements:
    """The test #907 said is worth more than three per-element assertions."""

    def test_no_built_Device_carries_an_element_R5_does_not_define(self):
        bad = []
        for r in _device_pairs():
            if r["resourceType"] != "Device":
                continue
            for k in r:
                if k not in R5_DEVICE_ELEMENTS:
                    bad.append(k)
        assert not bad, f"undefined on R5 Device: {sorted(set(bad))}"

    def test_no_built_DeviceUsage_carries_an_undefined_element(self):
        bad = []
        for r in _device_pairs():
            if r["resourceType"] != "DeviceUsage":
                continue
            for k in r:
                if k not in R5_DEVICEUSAGE_ELEMENTS:
                    bad.append(k)
        assert not bad, f"undefined on R5 DeviceUsage: {sorted(set(bad))}"

    def test_the_element_lists_themselves_exclude_the_wrong_names(self):
        """Guards the guard: if someone 'fixed' a failure by adding the bad
        name to these sets, the tests above would pass again."""
        assert "patient" not in R5_DEVICE_ELEMENTS
        assert "code" not in R5_DEVICE_ELEMENTS
        assert "subject" not in R5_DEVICEUSAGE_ELEMENTS
        assert "patient" in R5_DEVICEUSAGE_ELEMENTS
        assert "type" in R5_DEVICE_ELEMENTS

    def test_at_least_one_of_each_type_was_actually_examined(self):
        """Otherwise the two tests above pass by having nothing to check."""
        types = [r["resourceType"] for r in _device_pairs()]
        assert types.count("Device") >= 2
        assert types.count("DeviceUsage") >= 2


class TestTheThreeFixes:
    def test_1_the_generated_Device_has_no_patient(self):
        import datetime
        rows = rec._devices("Patient/x", datetime.date(1950, 1, 1),
                            random.Random(3))
        dev = [r for r in rows if r["resourceType"] == "Device"]
        assert dev, "the seed produced no device; pick another"
        assert "patient" not in dev[0]

    def test_2_the_generated_DeviceUsage_uses_patient_not_subject(self):
        import datetime
        rows = rec._devices("Patient/x", datetime.date(1950, 1, 1),
                            random.Random(3))
        use = [r for r in rows if r["resourceType"] == "DeviceUsage"]
        assert use
        assert use[0]["patient"] == {"reference": "Patient/x"}
        assert "subject" not in use[0]

    def test_3_the_absent_Device_codes_into_TYPE_not_code(self):
        body = rec._no_known("devices", "Device", "Patient/x", None,
                             "No known devices.")
        assert "type" in body
        assert "code" not in body
        assert body["type"]["coding"][0]["code"] == "no-known-devices"

    def test_the_absent_Device_carries_no_reference_at_all(self):
        """Because R5 gives it nowhere to put one."""
        body = rec._no_known("devices", "Device", "Patient/x", None,
                             "No known devices.")
        assert "patient" not in body
        assert "subject" not in body

    def test_the_other_absent_resources_still_carry_their_reference(self):
        """The subject_field=None path must not have silently dropped the
        reference for Immunization and Procedure, which DO define one."""
        imm = rec._no_known("immunisations", "Immunization", "Patient/x",
                            "patient", "No known immunisations.")
        assert imm["patient"] == {"reference": "Patient/x"}
        assert imm["vaccineCode"]["coding"][0]["code"] == \
            "no-known-immunizations"
        proc = rec._no_known("procedures", "Procedure", "Patient/x",
                             "subject", "No known procedures.")
        assert proc["subject"] == {"reference": "Patient/x"}
        assert proc["code"]["coding"][0]["code"] == "no-known-procedures"


class TestTheImplantTransportToo:
    def _a(self, **over):
        a = {"patient_guid": str(uuid.uuid4()), "subgroup": IMPLANT_SUBGROUP,
             "code_system": "urn:oid:1.2.752.116.1.1.1.1.3", "code": "Z95.0",
             "national_term": "Pacemaker", "asserted_at": "2019-04-12",
             "negation": False, "provenance": "documented"}
        a.update(over)
        return a

    def test_the_positive_path_puts_patient_on_the_USAGE_only(self):
        out = alert_implants.to_fhir(self._a(), patient_ref="Patient/p",
                                     device_id="d", usage_id="u")
        dev = [r for r in out if r["resourceType"] == "Device"][0]
        use = [r for r in out if r["resourceType"] == "DeviceUsage"][0]
        assert "patient" not in dev
        assert use["patient"] == {"reference": "Patient/p"}

    def test_the_NEGATED_path_emits_a_Device_with_no_reference_anywhere(self):
        """Decided deliberately: nothing is in use, so there is no
        DeviceUsage to carry the patient, and R5's Device cannot. The row's
        patient_guid is the only link — which is why the transport passes it
        explicitly."""
        out = alert_implants.to_fhir(self._a(negation=True),
                                     patient_ref="Patient/p", device_id="d")
        assert len(out) == 1
        assert out[0]["resourceType"] == "Device"
        assert "patient" not in out[0]
        assert "subject" not in out[0]

    def test_the_provenance_marker_survived_the_change(self):
        for neg in (False, True):
            out = alert_implants.to_fhir(
                self._a(negation=neg, provenance="simulated"),
                patient_ref="Patient/p", device_id="d", usage_id="u")
            for r in out:
                assert any(t["code"] == "simulated"
                           for t in r["meta"]["tag"])


class TestTheRowStillLinks:
    """Removing the element is only safe because the ROW carries the link."""

    @pytest.fixture
    def patient(self, client, db):
        fhir = FhirResource(resource_type="Patient",
                            resource_id=str(uuid.uuid4()),
                            resource_json={"resourceType": "Patient"})
        db.session.add(fhir)
        db.session.flush()
        p = PatientIndex(fhir_resource_guid=fhir.guid,
                         resource_id=str(uuid.uuid4()),
                         family_name="Devicesson", given_name="Test")
        db.session.add(p)
        db.session.commit()
        return p

    def test_the_generator_still_links_every_device_row(
            self, client, db, patient):
        """The generator passes patient_guid explicitly, which is what makes
        dropping Device.patient free rather than lossy."""
        from app.models.clinic import Clinic
        clinic = Clinic(name="907", organisation_guid=str(uuid.uuid4()),
                        is_active=True)
        db.session.add(clinic)
        db.session.commit()
        r = client.post("/admin/mock-data", data={
            "count": "12", "clinic_guid": str(clinic.guid)})
        assert r.status_code in (200, 302), r.status_code
        devs = db.session.query(FhirResource).filter(
            FhirResource.resource_type.in_(("Device", "DeviceUsage"))).all()
        assert devs, "no devices generated; raise the count"
        assert all(d.patient_guid is not None for d in devs)
        # and the JSON of each Device is clean of the removed element
        for d in devs:
            if d.resource_type == "Device":
                assert "patient" not in d.resource_json

    def test_a_bare_device_posted_with_query_patient_LINKS(
            self, client, db, patient):
        """The sharp edge, closed. Without `?patient=` a conformant bare R5
        Device would store with patient_guid NULL and be invisible to its own
        section."""
        r = client.post(
            f"/fhir/Device?patient={patient.resource_id}",
            json={"resourceType": "Device", "status": "active"})
        assert r.status_code == 201, r.get_data(as_text=True)
        row = db.session.query(FhirResource).filter_by(
            resource_id=r.get_json()["id"]).first()
        assert row.patient_guid == patient.guid

    def test_a_bare_device_posted_with_NOTHING_stores_unlinked(
            self, client, db, patient):
        """Asserted so the consequence is known rather than discovered. R5
        gives a bare Device nowhere to name a patient, so this is the
        standard's outcome, not a bug — and it is why `?patient=` exists."""
        r = client.post("/fhir/Device",
                        json={"resourceType": "Device", "status": "active"})
        assert r.status_code == 201
        row = db.session.query(FhirResource).filter_by(
            resource_id=r.get_json()["id"]).first()
        assert row.patient_guid is None

    def test_an_unknown_query_patient_is_a_404_not_a_silent_null(
            self, client, db, patient):
        r = client.post(f"/fhir/Device?patient={uuid.uuid4()}",
                        json={"resourceType": "Device", "status": "active"})
        assert r.status_code == 404

    def test_the_query_cannot_OVERRIDE_a_reference_in_the_body(
            self, client, db, patient):
        """Checked only when the body supplied nothing. A query parameter
        that could overrule the document would let a caller file one
        patient's resource under another."""
        other_fhir = FhirResource(resource_type="Patient",
                                  resource_id=str(uuid.uuid4()),
                                  resource_json={"resourceType": "Patient"})
        db.session.add(other_fhir)
        db.session.flush()
        other = PatientIndex(fhir_resource_guid=other_fhir.guid,
                             resource_id=str(uuid.uuid4()),
                             family_name="Annan", given_name="Test")
        db.session.add(other)
        db.session.commit()

        r = client.post(
            f"/fhir/DeviceUsage?patient={other.resource_id}",
            json={"resourceType": "DeviceUsage", "status": "active",
                  "patient": {"reference": f"Patient/{patient.resource_id}"}})
        assert r.status_code == 201, r.get_data(as_text=True)
        row = db.session.query(FhirResource).filter_by(
            resource_id=r.get_json()["id"]).first()
        assert row.patient_guid == patient.guid, "the body must win"
