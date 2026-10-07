"""#797 — 100 patients for an assigned care provider, as an undoable batch.

Generating is the easy half. The tests that matter are the purge ones, because
the delete order here is counter-intuitive in two ways and getting either
wrong loses or orphans data:

* `patient_index.fhir_resource_guid` -> `fhir_resources` cascades the OTHER
  way, so deleting the Patient resource removes the PatientIndex;
* `fhir_resources.patient_guid` has **no foreign key at all** (Rule 18), so
  clinical resources are never cascaded and a patients-only delete leaves
  every Condition and Observation orphaned, pointing at a patient that no
  longer exists.

`test_a_purge_leaves_nothing_behind` is the one that would catch both.
"""
from __future__ import annotations

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import euips_batch
from app.services import euips_sections as euips


def _clinic(db, name="Batch Clinic", org="org-batch-0001"):
    c = Clinic(name=name, organisation_guid=org, identifier=org, is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _generate(client, clinic, n, skip=False):
    data = {"clinic_guid": str(clinic.guid), "count": str(n)}
    if skip:
        data["skip_clinical"] = "on"
    resp = client.post("/admin/mock-data", data=data, follow_redirects=True)
    assert resp.status_code == 200
    return resp


class TestABatchIsIdentifiable:
    def test_every_patient_in_a_run_shares_one_batch_guid(self, client, db):
        _generate(client, _clinic(db), 8)
        guids = {p.generation_batch_guid
                 for p in _db.session.query(PatientIndex).all()}
        assert len(guids) == 1, guids
        assert None not in guids

    def test_two_runs_get_different_batch_guids(self, client, db):
        c = _clinic(db)
        _generate(client, c, 4)
        first = {p.generation_batch_guid
                 for p in _db.session.query(PatientIndex).all()}
        _generate(client, c, 4)
        allg = {p.generation_batch_guid
                for p in _db.session.query(PatientIndex).all()}
        assert len(allg) == 2, allg
        assert first < allg

    def test_the_batch_guid_is_reported_back(self, client, db):
        resp = _generate(client, _clinic(db), 3)
        guid = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        assert guid in resp.data.decode()

    def test_the_batch_list_counts_patients_resources_and_conformance(self, client, db):
        c = _clinic(db, name="Akademiska")
        _generate(client, c, 6)
        batches = euips_batch.list_batches()
        assert len(batches) == 1
        b = batches[0]
        assert b["patients"] == 6
        assert b["resources"] > 0
        assert b["clinic"] == "Akademiska"
        # "Fill in each header" means all of them, so the operator should see
        # 6/6 rather than infer it.
        assert b["conformant"] == 6, b


class TestTheProviderIsTheOrganisingUnit:
    def test_every_patient_is_assigned_to_the_chosen_clinic(self, client, db):
        c = _clinic(db)
        _generate(client, c, 10)
        for p in _db.session.query(PatientIndex).all():
            rows = (_db.session.query(PatientClinicAssignment)
                    .filter(PatientClinicAssignment.patient_guid == p.guid).all())
            assert [a.clinic_guid for a in rows] == [c.guid], rows

    def test_the_managing_organisation_matches_the_assignment(self, client, db):
        """Three places could hold this one fact -- the assignment, the FHIR
        managingOrganization and the Composition custodian. #768 is what
        happens when three organisation identifiers on one datapoint disagree,
        so they must all name the same org."""
        c = _clinic(db)
        _generate(client, c, 5)
        for p in _db.session.query(PatientIndex).all():
            rj = p.fhir_resource.resource_json
            ref = (rj.get("managingOrganization") or {}).get("reference")
            assert ref == f"Organization/{c.organisation_guid}", ref


class TestThePurge:
    def test_a_purge_leaves_nothing_behind(self, client, db):
        """THE test. Both cascade traps would show up here."""
        c = _clinic(db)
        _generate(client, c, 8)
        batch = str(_db.session.query(PatientIndex).first().generation_batch_guid)

        before_resources = _db.session.query(FhirResource).count()
        assert before_resources > 8

        removed = euips_batch.purge_batch(batch)
        assert removed is not None
        assert removed["patients"] == 8

        assert _db.session.query(PatientIndex).count() == 0
        # The one a patients-only delete would miss: no FK, no cascade.
        assert _db.session.query(FhirResource).count() == 0, \
            "clinical resources orphaned -- fhir_resources.patient_guid has no FK"
        assert _db.session.query(PatientClinicAssignment).count() == 0
        assert _db.session.query(IpsCard).count() == 0
        assert _db.session.query(IpsSnapshot).count() == 0

    def test_a_purge_touches_only_its_own_batch(self, client, db):
        c = _clinic(db)
        _generate(client, c, 5)
        keep = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        _generate(client, c, 5)
        batches = {str(p.generation_batch_guid)
                   for p in _db.session.query(PatientIndex).all()}
        doomed = next(b for b in batches if b != keep)

        euips_batch.purge_batch(doomed)

        left = _db.session.query(PatientIndex).all()
        assert len(left) == 5
        assert {str(p.generation_batch_guid) for p in left} == {keep}
        # And the survivors keep their resources.
        for p in left:
            assert (_db.session.query(FhirResource)
                    .filter(FhirResource.patient_guid == p.guid).count()) > 0

    def test_it_never_touches_a_patient_with_no_batch(self, client, db):
        """The 150 pre-existing production patients have NULL, which correctly
        means "not from a tracked batch". A purge must not reach them."""
        c = _clinic(db)
        _generate(client, c, 4)
        batch = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        # An untracked patient, as the live rows are.
        res = FhirResource(resource_type="Patient", resource_id="legacy-1",
                           resource_json={"resourceType": "Patient",
                                          "id": "legacy-1"})
        _db.session.add(res)
        _db.session.flush()
        legacy = PatientIndex(fhir_resource_guid=res.guid,
                              resource_id="legacy-1", family_name="Legacy")
        _db.session.add(legacy)
        _db.session.commit()

        euips_batch.purge_batch(batch)

        survivors = _db.session.query(PatientIndex).all()
        assert [p.family_name for p in survivors] == ["Legacy"]
        assert survivors[0].generation_batch_guid is None

    def test_an_unknown_batch_deletes_nothing(self, client, db):
        c = _clinic(db)
        _generate(client, c, 3)
        before = _db.session.query(PatientIndex).count()
        assert euips_batch.purge_batch("11111111-2222-3333-4444-555555555555") is None
        assert euips_batch.purge_batch("not-a-uuid") is None
        assert _db.session.query(PatientIndex).count() == before

    def test_the_preview_reports_without_deleting(self, client, db):
        """Counts before consent: the operator agrees to a number, not a word."""
        c = _clinic(db)
        _generate(client, c, 6)
        batch = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        before = _db.session.query(FhirResource).count()
        p = euips_batch.batch_preview(batch)
        assert p["patients"] == 6
        assert p["clinical_resources"] > 0
        assert _db.session.query(FhirResource).count() == before, "preview wrote"

    def test_the_purge_route_requires_an_explicit_batch_guid(self, client, db):
        """No "purge the last one" and no "purge all": either would make a
        mistake cheap to commit and expensive to notice."""
        c = _clinic(db)
        _generate(client, c, 3)
        resp = client.post("/admin/mock-data/purge", data={},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert _db.session.query(PatientIndex).count() == 3

    def test_the_route_purges_and_says_what_it_removed(self, client, db):
        c = _clinic(db)
        _generate(client, c, 4)
        batch = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        resp = client.post("/admin/mock-data/purge",
                           data={"batch_guid": batch}, follow_redirects=True)
        body = resp.data.decode()
        assert "Purged batch" in body
        assert "4 patients" in body
        assert _db.session.query(PatientIndex).count() == 0


class TestOneHundredPerProvider:
    def test_a_hundred_patients_are_all_conformant(self, client, db):
        """The operator's actual request: "fill in each header for up to 100
        patients for an assigned care provider"."""
        c = _clinic(db)
        _generate(client, c, 100)
        patients = _db.session.query(PatientIndex).all()
        assert len(patients) == 100
        guids = [p.guid for p in patients]
        assert euips_batch.conformant_count(guids) == 100

    def test_a_hundred_patients_share_one_batch_and_one_clinic(self, client, db):
        c = _clinic(db)
        _generate(client, c, 100)
        assert len({p.generation_batch_guid
                    for p in _db.session.query(PatientIndex).all()}) == 1
        assert (_db.session.query(PatientClinicAssignment)
                .filter(PatientClinicAssignment.clinic_guid == c.guid)
                .count()) == 100

    def test_names_are_unique_within_a_batch(self, client, db):
        """Per batch, not globally -- a documented decision. Two batches may
        repeat a name; one batch must not."""
        c = _clinic(db)
        _generate(client, c, 100)
        names = [(p.family_name, p.given_name)
                 for p in _db.session.query(PatientIndex).all()]
        assert len(names) == len(set(names)), "duplicate name within one batch"

    def test_a_hundred_can_be_purged_in_one_go(self, client, db):
        c = _clinic(db)
        _generate(client, c, 100)
        batch = str(_db.session.query(PatientIndex).first().generation_batch_guid)
        removed = euips_batch.purge_batch(batch)
        assert removed["patients"] == 100
        assert _db.session.query(PatientIndex).count() == 0
        assert _db.session.query(FhirResource).count() == 0
