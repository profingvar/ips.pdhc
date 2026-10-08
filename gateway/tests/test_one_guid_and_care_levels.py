"""The operator principle of 2026-10-08, as tests.

> Patient information must be reachable by THE guid wherever it is in the
> platform, and a guid must have a 1:1 relation to a personnummer, a caregiver
> and a careunit. If careunit is not given then the careunit should be set to
> the caregiver.

Measured before this change: **150 of 150** patients carried two different
identifiers, and ips could not name a caregiver at all — the hierarchy existed
only in sso, so an assignment recorded one unlabelled organisation.
"""
import uuid

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex
from app.services import care_hierarchy_sync as sync_mod
from app.services.fhir_service import create_resource


def _mk_patient(db, pnr="19580314-8691"):
    rid = str(uuid.uuid4())
    create_resource("Patient", {
        "resourceType": "Patient", "id": rid,
        "name": [{"family": "Ek", "given": ["Ann"]}],
        "gender": "female", "birthDate": "1958-03-14",
        "identifier": [{"system": "urn:oid:1.2.752.129.2.1.3.1",
                        "value": pnr}]})
    db.session.commit()
    return db.session.query(PatientIndex).filter_by(resource_id=rid).first()


class TestOneGuidPerPatient:
    def test_the_platform_guid_EQUALS_the_fhir_resource_id(self, client, db):
        """The whole of rule 1. Before this, two independent uuid4s."""
        p = _mk_patient(db)
        assert str(p.guid) == str(p.resource_id), (
            "a patient still carries two identifiers")

    def test_both_lookup_paths_reach_the_same_patient(self, client, db):
        """Rule 1 is about REACHABILITY, so exercise both routes."""
        p = _mk_patient(db)
        a = client.get("/api/v1/patients/%s/euips-header" % p.guid)
        b = client.get("/fhir/Patient/%s" % p.resource_id)
        assert a.status_code == 200
        assert b.status_code == 200
        assert a.get_json()["patient_guid"] == str(p.guid)
        assert b.get_json()["id"] == str(p.guid)

    def test_a_non_uuid_resource_id_does_not_crash_the_write(self, client, db):
        """`guid` is a UUID column: handing it a non-UUID would 500 (#805).

        Such a patient DOES end up with two identifiers — a conformance breach
        — but the write must survive and log, not fail.
        """
        create_resource("Patient", {
            "resourceType": "Patient", "id": "not-a-uuid",
            "name": [{"family": "Odd"}], "gender": "other",
            "birthDate": "1960-01-01"})
        db.session.commit()
        p = db.session.query(PatientIndex).filter_by(
            resource_id="not-a-uuid").first()
        assert p is not None
        assert str(p.guid) != p.resource_id   # unavoidable, and logged


class TestCareLevels:
    def _clinic(self, db, name, org, parent=None):
        c = Clinic(name=name, organisation_guid=org, identifier=org,
                   is_active=True, care_organisation_guid=parent)
        db.session.add(c)
        db.session.commit()
        return c

    def test_a_unit_reports_both_levels_distinctly(self, client, db):
        c = self._clinic(db, "Alfa VC", "org-unit-1", parent="org-care-1")
        d = c.to_dict()
        assert d["care_unit_guid"] == "org-unit-1"
        assert d["care_organisation_guid"] == "org-care-1"
        assert d["is_own_caregiver"] is False

    def test_careunit_equals_caregiver_is_reported_as_own_caregiver(self,
                                                                    client, db):
        """The operator's fallback, stored explicitly."""
        c = self._clinic(db, "Region X", "org-care-2", parent="org-care-2")
        d = c.to_dict()
        assert d["care_unit_guid"] == d["care_organisation_guid"]
        assert d["is_own_caregiver"] is True

    def test_an_unsynced_clinic_is_treated_as_its_own_caregiver(self, client,
                                                               db):
        """NULL must be SAFE, not wrong.

        A clinic whose caregiver has not been synced yet reads NULL. Treating
        that as "it is its own caregiver" is the operator's fallback, so an
        unsynced row degrades to the correct answer instead of claiming no
        caregiver exists.
        """
        c = self._clinic(db, "Unsynced", "org-unit-3", parent=None)
        assert c.is_own_caregiver() is True
        assert c.to_dict()["is_own_caregiver"] is True

    def test_both_levels_appear_on_the_patient_clinic_list(self, client, db):
        """The endpoint consumers actually use."""
        from app.models.patient_index import PatientClinicAssignment
        c = self._clinic(db, "Beta VC", "org-unit-4", parent="org-care-4")
        p = _mk_patient(db)
        db.session.add(PatientClinicAssignment(patient_guid=p.guid,
                                               clinic_guid=c.guid))
        db.session.commit()
        r = client.get("/api/v1/patients/%s/clinics" % p.guid)
        assert r.status_code == 200
        row = r.get_json()[0]
        assert row["care_unit_guid"] == "org-unit-4"
        assert row["care_organisation_guid"] == "org-care-4"


class TestSyncAppliesTheFallback:
    def _clinic(self, db, name, org):
        c = Clinic(name=name, organisation_guid=org, identifier=org,
                   is_active=True)
        db.session.add(c)
        db.session.commit()
        return c

    def test_a_unit_gets_its_sso_parent(self, client, db, monkeypatch):
        c = self._clinic(db, "Alfa", "unit-a")
        monkeypatch.setattr(sync_mod, "_sso_get", lambda path, token: (
            [{"care_unit_guid": "unit-a", "care_organisation_guid": "care-a"}]
            if "care-units" in path else
            [{"care_organisation_guid": "care-a"}]))
        sync_mod.sync("tok", dry_run=False)
        assert c.care_organisation_guid == "care-a"

    def test_a_caregiver_is_set_equal_to_itself(self, client, db, monkeypatch):
        """careunit := caregiver, written rather than recomputed per reader."""
        c = self._clinic(db, "Region", "care-b")
        monkeypatch.setattr(sync_mod, "_sso_get", lambda path, token: (
            [] if "care-units" in path else
            [{"care_organisation_guid": "care-b"}]))
        sync_mod.sync("tok", dry_run=False)
        assert c.care_organisation_guid == "care-b"
        assert c.is_own_caregiver() is True

    def test_an_org_sso_does_not_know_is_LEFT_ALONE(self, client, db,
                                                    monkeypatch):
        """Guessing a parent would assert a legal relationship."""
        c = self._clinic(db, "Stranger", "org-unknown")
        monkeypatch.setattr(sync_mod, "_sso_get",
                            lambda path, token: [] if "care-units" in path
                            else [{"care_organisation_guid": "care-c"}])
        rep = sync_mod.sync("tok", dry_run=False)
        assert c.care_organisation_guid is None
        assert any(u.get("org_guid") == "org-unknown"
                   for u in rep["unresolved"])

    def test_dry_run_writes_nothing(self, client, db, monkeypatch):
        c = self._clinic(db, "Alfa", "unit-d")
        monkeypatch.setattr(sync_mod, "_sso_get", lambda path, token: (
            [{"care_unit_guid": "unit-d", "care_organisation_guid": "care-d"}]
            if "care-units" in path else
            [{"care_organisation_guid": "care-d"}]))
        rep = sync_mod.sync("tok", dry_run=True)
        assert c.care_organisation_guid is None
        assert len(rep["would_change"]) == 1

    def test_no_token_aborts_without_writing(self, client, db, app):
        """A missing token must be NAMED as ours, not blamed on sso.

        SSO_BASE_URL is set here on purpose: without it the base-url check
        fires first and the test would pass on the wrong branch, proving
        nothing about the token path.
        """
        import pytest
        c = self._clinic(db, "Alfa", "unit-e")
        app.config["SSO_BASE_URL"] = "https://sso.test"
        with pytest.raises(sync_mod.SsoHierarchyUnavailable) as e:
            sync_mod.sync(None, dry_run=False)
        msg = str(e.value).lower()
        assert "missing credential" in msg
        assert "bearer" in msg, "it should say which header sso reads"
        assert c.care_organisation_guid is None

    def test_an_sso_outage_aborts_without_half_applying(self, client, db, app,
                                                        monkeypatch):
        """A sync that writes some rows and then fails is worse than one that
        writes none: the hierarchy would be half-mirrored with no record of
        where it stopped."""
        import pytest
        c = self._clinic(db, "Alfa", "unit-f")
        app.config["SSO_BASE_URL"] = "https://sso.test"
        monkeypatch.setattr(sync_mod, "_sso_get", lambda path, token: (
            _ for _ in ()).throw(sync_mod.SsoHierarchyUnavailable("sso 503")))
        with pytest.raises(sync_mod.SsoHierarchyUnavailable):
            sync_mod.sync("tok", dry_run=False)
        assert c.care_organisation_guid is None
