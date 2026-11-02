"""#883 — `Device` and `DeviceUsage` were invisible to the FHIR API.

EPS makes section 46264-8 (medical devices and implants) **1..1**, so these
resources must be writable and advertised. The gap was narrower than the
assessment stated, and the correction matters because it changes what the fix
is:

  - they were already GENERATED (`euips_recommended._devices`, since #794)
  - they were already STORABLE (`fhir_resources.resource_type` is a free
    `String(64)`)
  - they were absent only from `SUPPORTED_RESOURCE_TYPES`, which gates the
    generic `/fhir/<type>` handler and feeds `_default_capability_statement`

So the HTTP API refused them and the CapabilityStatement never mentioned them,
while rows existed. **Visibility, not existence.** The stale catalogue note
that said no Device type existed at all was removed by #898.

`DeviceUsage`, never `DeviceUseStatement`: the legacy spelling is accepted on
READ only (#898) and must never reach this list, because
`test_capability_truth.py` asserts the list and the CapabilityStatement agree
in both directions — a legacy name here would be pinned as correct rather than
caught.
"""
from __future__ import annotations

import random

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.services import euips_recommended as rec
from app.services.fhir_service import SUPPORTED_RESOURCE_TYPES

LEGACY = "DeviceUseStatement"


def _patient(client):
    resp = client.post("/fhir/Patient", json={
        "resourceType": "Patient",
        "name": [{"family": "Enhetsson", "given": ["Dev"]}],
        "gender": "other",
        "birthDate": "1970-01-01",
        # Checksum DELIBERATELY invalid, like the other fixtures in this
        # suite: this repo is public and a valid personnummer could belong to a
        # real person (#405 confinement). Do not "correct" it.
        "identifier": [{"system": "urn:oid:1.2.752.129.2.1.3.1",
                        "value": "197001011234"}],
    })
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _row(resource_type, resource_id):
    return (_db.session.query(FhirResource)
            .filter(FhirResource.resource_type == resource_type,
                    FhirResource.resource_id == resource_id)
            .first())


class TestTheTypesAreSupportedAndAdvertised:
    def test_both_are_in_the_supported_list(self):
        assert "Device" in SUPPORTED_RESOURCE_TYPES
        assert "DeviceUsage" in SUPPORTED_RESOURCE_TYPES

    def test_both_are_advertised_in_the_CapabilityStatement(self, client):
        """Through the route, not by reading the list. Asserting the
        ingredient is not asserting the dish."""
        cs = client.get("/fhir/metadata").get_json()
        advertised = {r["type"] for r in cs["rest"][0]["resource"]}
        assert "Device" in advertised, sorted(advertised)
        assert "DeviceUsage" in advertised, sorted(advertised)

    def test_the_LEGACY_spelling_is_neither_supported_nor_advertised(self, client):
        assert LEGACY not in SUPPORTED_RESOURCE_TYPES
        cs = client.get("/fhir/metadata").get_json()
        advertised = {r["type"] for r in cs["rest"][0]["resource"]}
        assert LEGACY not in advertised


class TestTheWritePathLinksThePatient:
    def test_a_Device_links_via_its_patient_field(self, client, db):
        """R5 Device carries no `subject`. The create route already had a
        `patient` fallback — this pins that it keeps working for the newly
        admitted type, because an unlinked row has patient_guid NULL and falls
        out of every patient-scoped read and Rule 24 scope."""
        pid = _patient(client)
        resp = client.post("/fhir/Device", json={
            "resourceType": "Device",
            "patient": {"reference": f"Patient/{pid}"},
            "status": "active",
        })
        assert resp.status_code == 201, resp.get_data(as_text=True)
        row = _row("Device", resp.get_json()["id"])
        assert row is not None
        assert row.patient_guid is not None, "Device stored with no patient link"

    def test_a_DeviceUsage_links_via_its_subject_field(self, client, db):
        pid = _patient(client)
        resp = client.post("/fhir/DeviceUsage", json={
            "resourceType": "DeviceUsage",
            "subject": {"reference": f"Patient/{pid}"},
            "status": "active",
        })
        assert resp.status_code == 201, resp.get_data(as_text=True)
        row = _row("DeviceUsage", resp.get_json()["id"])
        assert row is not None
        assert row.patient_guid is not None

    def test_a_resource_with_NEITHER_field_is_stored_UNLINKED(self, client, db):
        """The control on the two above: linkage comes from the body, not from
        the type being admitted. A silent NULL here is the failure mode worth
        knowing about, so it is pinned rather than assumed away."""
        resp = client.post("/fhir/Device", json={
            "resourceType": "Device", "status": "active",
        })
        assert resp.status_code == 201
        row = _row("Device", resp.get_json()["id"])
        assert row.patient_guid is None


class TestTheGeneratorsOutputRoundTrips:
    def test_every_body_the_device_builder_produces_is_accepted(self, client, db):
        """The builder has produced these since #794 and the API refused them.
        Posting its own output is the end-to-end form of this ticket."""
        pid = _patient(client)
        bodies = rec._devices(f"Patient/{pid}", None, random.Random(11))
        assert bodies, "builder produced nothing to test"
        for b in bodies:
            rt = b["resourceType"]
            resp = client.post(f"/fhir/{rt}", json=b)
            assert resp.status_code == 201, \
                f"{rt} refused: {resp.get_data(as_text=True)}"

    def test_a_device_is_findable_by_patient_search(self, client, db):
        pid = _patient(client)
        client.post("/fhir/Device", json={
            "resourceType": "Device",
            "patient": {"reference": f"Patient/{pid}"},
            "status": "active",
        })
        bundle = client.get(f"/fhir/Device?patient={pid}").get_json()
        assert bundle["total"] >= 1, bundle


class TestTheLegacySpellingIsRefusedAtTheApi:
    def test_posting_DeviceUseStatement_is_not_supported(self, client):
        """Accept-both applies to READING stored rows (#898), not to admitting
        new ones. A producer sending the R4 name must be told, not quietly
        accommodated — otherwise the alias never becomes removable."""
        resp = client.post(f"/fhir/{LEGACY}", json={"resourceType": LEGACY})
        assert resp.status_code != 201
        issue = resp.get_json()["issue"][0]
        assert issue["code"] == "not-supported", issue
        assert LEGACY in issue["diagnostics"], issue
