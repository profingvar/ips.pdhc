"""The custodian must equal the ASSIGNMENT — #792's watch item.

Three places hold one organisation: the Composition custodian, the Patient's
`managingOrganization`, and the `PatientClinicAssignment` row. #792 says to
state which is authoritative and derive the rest, because this is the #768
shape — three organisation identifiers on one datapoint that failed to
collapse, after which a Rule 24 gate scoped on the wrong org.

A test asserting merely "custodian is set" would pass with the custodian set
to the wrong organisation, which is the whole failure mode. So these go
through the real generator and compare the custodian against the assignment
specifically, including the case where `managingOrganization` is deliberately
made stale.
"""
import uuid

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import euips_header as hdr
from app.services.fhir_service import create_resource
from app.services.ips_generator import (
    custodian_disagreement, generate_ips_bundle, _custodian_clinic,
)


def _clinic(db, name="Assigned Vårdcentral", org="org-assigned-0001"):
    c = Clinic(name=name, organisation_guid=org, identifier=org,
               is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _patient(db, clinic, managing_org):
    """A patient whose managingOrganization is set independently of the
    assignment, so the two can be made to disagree on purpose."""
    rid = str(uuid.uuid4())
    create_resource("Patient", {
        "resourceType": "Patient",
        "id": rid,
        "name": [{"family": "Lind", "given": ["Eva"]}],
        "gender": "female",
        "birthDate": "1980-05-05",
        "identifier": [{"system": hdr.PERSONNUMMER_SYSTEM,
                        "value": "19800505-0000"}],
        "managingOrganization": {"reference": "Organization/%s" % managing_org},
        "communication": hdr.patient_communication("sv-SE"),
    })
    db.session.commit()
    p = db.session.query(PatientIndex).filter_by(resource_id=rid).first()
    if clinic is not None:
        db.session.add(PatientClinicAssignment(patient_guid=p.guid,
                                               clinic_guid=clinic.guid))
        db.session.commit()
    return p


def _composition(bundle):
    for e in bundle["entry"]:
        if e["resource"].get("resourceType") == "Composition":
            return e["resource"]
    raise AssertionError("no Composition in the bundle")


class TestCustodianComesFromTheAssignment:
    def test_custodian_is_the_assigned_organisation(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        comp = _composition(generate_ips_bundle(p))
        assert comp["custodian"]["display"] == c.name
        assert comp["custodian"]["reference"] == "urn:uuid:%s" % (
            c.organisation_guid)

    def test_a_stale_managing_organisation_does_not_win(self, client, db):
        """The ASSIGNMENT is authoritative, so a mismatched
        managingOrganization must not change the custodian."""
        c = _clinic(db)
        p = _patient(db, c, managing_org="org-STALE-9999")
        comp = _composition(generate_ips_bundle(p))
        assert comp["custodian"]["reference"] == "urn:uuid:%s" % (
            c.organisation_guid)
        assert "STALE" not in comp["custodian"]["reference"]

    def test_the_disagreement_is_REPORTED_not_swallowed(self, client, db):
        """#768 happened because a mismatch was invisible.

        Preferring the right source silently is only half a fix: an operator
        has to be able to see that the Patient resource is stale, or it stays
        stale forever.
        """
        c = _clinic(db)
        p = _patient(db, c, managing_org="org-STALE-9999")
        bundle = generate_ips_bundle(p)
        tags = bundle["meta"].get("tag") or []
        assert any(t["code"] == "custodian-mismatch" for t in tags), (
            "a custodian/managingOrganization mismatch produced no warning")
        msg = [t["display"] for t in tags
               if t["code"] == "custodian-mismatch"][0]
        assert "org-STALE-9999" in msg and c.organisation_guid in msg
        assert "assignment wins" in msg

    def test_agreement_produces_no_warning_tag(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        bundle = generate_ips_bundle(p)
        tags = bundle["meta"].get("tag") or []
        assert not any(t["code"] == "custodian-mismatch" for t in tags)

    def test_no_assignment_means_no_custodian_and_no_invention(self, client,
                                                               db):
        """A patient with no assignment has no custodian.

        Inventing one would make the header contradict the assignment table —
        the divergence this whole file exists to prevent.
        """
        p = _patient(db, None, managing_org="org-orphan-1")
        assert _custodian_clinic(p) is None
        comp = _composition(generate_ips_bundle(p))
        for forbidden in ("custodian", "author", "attester"):
            assert forbidden not in comp, (
                "%s was emitted for a patient with no clinic assignment"
                % forbidden)

    def test_inactive_clinic_is_not_a_custodian(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        c.is_active = False
        db.session.commit()
        assert _custodian_clinic(p) is None

    def test_disagreement_helper_is_quiet_when_there_is_nothing_to_say(self):
        c = type("C", (), {"organisation_guid": "o1", "name": "N"})()
        assert custodian_disagreement(
            {"managingOrganization": {"reference": "Organization/o1"}}, c
        ) is None
        assert custodian_disagreement({}, c) is None
        assert custodian_disagreement({}, None) is None


class TestHeaderResourcesTravelInTheBundle:
    def test_related_person_and_coverage_are_entries(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        create_resource("RelatedPerson",
                        hdr.related_person_resources(
                            "Patient/%s" % p.resource_id, family="Lind",
                            birth_date="1980-05-05")[0],
                        patient_guid=p.guid)
        create_resource("Coverage",
                        hdr.coverage_resource("Patient/%s" % p.resource_id,
                                              city="Uppsala"),
                        patient_guid=p.guid)
        db.session.commit()

        bundle = generate_ips_bundle(p)
        types = [e["resource"].get("resourceType") for e in bundle["entry"]]
        assert "RelatedPerson" in types
        assert "Coverage" in types
        assert "Organization" in types, "the custodian must be resolvable"

    def test_header_resources_are_NOT_clinical_sections(self, client, db):
        """A 'Coverage section' is a section the guideline does not define.

        They are fetched separately from the clinical types for this reason;
        if they ever reach `_build_sections` the document grows sections that
        no euIPS consumer expects.
        """
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        create_resource("Coverage",
                        hdr.coverage_resource("Patient/%s" % p.resource_id),
                        patient_guid=p.guid)
        db.session.commit()

        comp = _composition(generate_ips_bundle(p))
        blob = str(comp.get("section", []))
        assert "Coverage" not in blob
        assert "RelatedPerson" not in blob

    def test_language_round_trips_from_the_patient(self, client, db):
        """A regenerated summary must not change language.

        The Composition reads it back from Patient.communication rather than
        drawing again, so two generations agree.
        """
        c = _clinic(db)
        rid = str(uuid.uuid4())
        create_resource("Patient", {
            "resourceType": "Patient", "id": rid,
            "name": [{"family": "Niemi"}], "gender": "male",
            "birthDate": "1975-02-02",
            "communication": hdr.patient_communication("fi-FI"),
        })
        db.session.commit()
        p = db.session.query(PatientIndex).filter_by(resource_id=rid).first()
        db.session.add(PatientClinicAssignment(patient_guid=p.guid,
                                               clinic_guid=c.guid))
        db.session.commit()

        first = _composition(generate_ips_bundle(p))["language"]
        second = _composition(generate_ips_bundle(p))["language"]
        assert first == second == "fi-FI"

    def test_language_defaults_when_the_patient_carries_none(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        res = (db.session.query(FhirResource)
               .filter_by(resource_type="Patient", resource_id=p.resource_id)
               .first())
        body = dict(res.resource_json)
        body.pop("communication", None)
        res.resource_json = body
        db.session.commit()
        assert _composition(generate_ips_bundle(p))["language"] == "sv-SE"


class TestGeneratorProducesHeaders:
    """Through the real admin POST, not by calling the helpers.

    #792 is only delivered if a GENERATED patient has a header. Asserting the
    helper returns a Coverage proves nothing about the generator — the #729
    lesson: test the dish, not the ingredient.
    """

    def test_a_generated_cohort_has_contacts_and_insurance(self, client, db):
        c = _clinic(db)
        resp = client.post("/admin/mock-data",
                           data={"clinic_guid": str(c.guid), "count": "12"},
                           follow_redirects=True)
        assert resp.status_code == 200

        patients = db.session.query(PatientIndex).all()
        assert patients
        for p in patients:
            rows = (db.session.query(FhirResource)
                    .filter(FhirResource.patient_guid == p.guid).all())
            types = {r.resource_type for r in rows}
            assert "RelatedPerson" in types, (
                "generated patient %s has no contact person" % p.guid)
            assert "Coverage" in types, (
                "generated patient %s has no health insurance" % p.guid)

    def test_skip_clinical_still_gets_a_header(self, client, db):
        """The header is not clinical content.

        skip_clinical exists so sim.pdhc can own the observations; a patient
        handed over for clinical data still needs a custodian, a contact and
        insurance, or the document is not a document.
        """
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "6",
                          "skip_clinical": "on"},
                    follow_redirects=True)
        for p in db.session.query(PatientIndex).all():
            types = {r.resource_type for r in
                     db.session.query(FhirResource)
                     .filter(FhirResource.patient_guid == p.guid).all()}
            assert {"RelatedPerson", "Coverage"} <= types, types

    def test_no_adult_in_a_cohort_gets_a_guardian(self, client, db):
        """The data-quality rule, enforced over a real cohort."""
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "40"},
                    follow_redirects=True)
        offenders = []
        for p in db.session.query(PatientIndex).all():
            rows = (db.session.query(FhirResource)
                    .filter(FhirResource.patient_guid == p.guid)
                    .filter(FhirResource.resource_type.in_(
                        ["Patient", "RelatedPerson"])).all())
            pj = next((r.resource_json for r in rows
                       if r.resource_type == "Patient"), {})
            has_guard = any(
                cod.get("code") == "GUARD"
                for r in rows if r.resource_type == "RelatedPerson"
                for rel in r.resource_json.get("relationship", ())
                for cod in rel.get("coding", ()))
            age = hdr.age_on(pj.get("birthDate"))
            if has_guard and (age is None or age >= hdr.AGE_OF_MAJORITY):
                offenders.append((p.guid, age))
        assert not offenders, (
            "guardians attached to adults: %s" % offenders)


class TestHeaderEndpoint:
    def test_reports_a_complete_header_for_a_generated_patient(self, client,
                                                               db):
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "3"},
                    follow_redirects=True)
        p = db.session.query(PatientIndex).first()

        r = client.get("/api/v1/patients/%s/euips-header" % p.guid)
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["complete"], body["missing"]
        assert body["custodian"]["organisation_guid"] == c.organisation_guid
        assert body["custodian_mismatch"] is None
        assert body["codes_verified"] is False
        assert "NOT a claim of EU/EHDS conformance" in body["disclaimer"]

    def test_reports_the_mismatch_rather_than_hiding_it(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org="org-STALE-9999")
        r = client.get("/api/v1/patients/%s/euips-header" % p.guid)
        assert r.status_code == 200
        body = r.get_json()
        assert body["custodian_mismatch"]
        assert "org-STALE-9999" in body["custodian_mismatch"]
        # The authoritative source still wins.
        assert body["custodian"]["organisation_guid"] == c.organisation_guid

    def test_malformed_guid_is_400_not_500(self, client, db):
        """#730: a gate must answer with a verdict, not an exception."""
        assert client.get(
            "/api/v1/patients/not-a-uuid/euips-header").status_code == 400

    def test_unknown_patient_is_404(self, client, db):
        assert client.get(
            "/api/v1/patients/%s/euips-header" % uuid.uuid4()
        ).status_code == 404


class TestBackfill:
    """#792 backfill — the header is half derived, half stored.

    Deploying #792 gave every existing patient a custodian, author, attester
    and language immediately, because those are computed on read. It gave none
    of them a RelatedPerson or a Coverage, because those are stored. Verified
    on production: a real patient reported
    `missing: ['contact_person', 'health_insurance']`.
    """

    def test_dry_run_writes_nothing(self, client, db):
        from app.services import euips_header_backfill as bf
        c = _clinic(db)
        _patient(db, c, managing_org=c.organisation_guid)
        before = db.session.query(FhirResource).count()

        out = bf.run(dry_run=True)
        assert out["dry_run"] is True
        assert out["need_related"] >= 1
        assert out["need_coverage"] >= 1
        assert db.session.query(FhirResource).count() == before, (
            "a dry run wrote to the database")

    def test_apply_creates_the_missing_header(self, client, db):
        from app.services import euips_header_backfill as bf
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)

        out = bf.run(dry_run=False, seed=7)
        assert out["created"]["Coverage"] >= 1
        assert out["created"]["RelatedPerson"] >= 1

        types = {r.resource_type for r in db.session.query(FhirResource)
                 .filter(FhirResource.patient_guid == p.guid).all()}
        assert {"RelatedPerson", "Coverage"} <= types

        r = client.get("/api/v1/patients/%s/euips-header" % p.guid)
        assert r.get_json()["complete"], r.get_json()["missing"]

    def test_running_twice_is_a_no_op(self, client, db):
        """The first thing anyone does with a backfill is run it again."""
        from app.services import euips_header_backfill as bf
        c = _clinic(db)
        _patient(db, c, managing_org=c.organisation_guid)

        bf.run(dry_run=False, seed=7)
        after_first = db.session.query(FhirResource).count()
        second = bf.run(dry_run=False, seed=7)
        assert second["created"] == {"RelatedPerson": 0, "Coverage": 0}
        assert db.session.query(FhirResource).count() == after_first

    def test_backfill_never_invents_an_adult_guardian(self, client, db):
        from app.services import euips_header_backfill as bf
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)  # born 1980
        bf.run(dry_run=False, seed=7)
        guards = [
            cod for r in db.session.query(FhirResource)
            .filter(FhirResource.patient_guid == p.guid)
            .filter(FhirResource.resource_type == "RelatedPerson").all()
            for rel in r.resource_json.get("relationship", ())
            for cod in rel.get("coding", ()) if cod.get("code") == "GUARD"]
        assert not guards

    def test_language_is_stored_so_it_does_not_change_on_reread(self, client,
                                                                db):
        from app.services import euips_header_backfill as bf
        c = _clinic(db)
        rid = str(uuid.uuid4())
        create_resource("Patient", {
            "resourceType": "Patient", "id": rid,
            "name": [{"family": "Ek"}], "gender": "male",
            "birthDate": "1970-01-01"})          # no communication
        db.session.commit()
        p = db.session.query(PatientIndex).filter_by(resource_id=rid).first()
        db.session.add(PatientClinicAssignment(patient_guid=p.guid,
                                               clinic_guid=c.guid))
        db.session.commit()

        bf.run(dry_run=False, seed=7)
        first = _composition(generate_ips_bundle(p))["language"]
        second = _composition(generate_ips_bundle(p))["language"]
        assert first == second


class TestClinicsLookupAcceptsEitherIdentifier:
    """ips keeps TWO identifiers for one patient, and consumers hold either.

    `PatientIndex.guid` is the platform identifier every other service uses;
    `resource_id` is the FHIR id that `/fhir/Patient/<id>` is keyed by. They
    are different values for the same person — the #771 shape.

    This was not theoretical. request.pdhc's patient pages are built on the
    FHIR id, so `GET /api/v1/patients/<that id>/clinics` returned
    404 "Patient not found" for a patient who plainly exists, and the page
    could not reach the assignment it needed to display. Confirmed on
    production 2026-10-08: resource_id 612a2995-… , index guid eaf95fd1-… .
    """

    def test_new_patients_now_carry_ONE_identifier(self, client, db):
        """This assertion was inverted on 2026-10-08, deliberately.

        It used to read `assert p.guid != p.resource_id`, pinning the premise
        of the dual lookup: two independent uuid4s per patient. The operator
        principle then made one guid the rule — "patient information must be
        reachable by THE guid wherever it is in the platform" — so
        `fhir_service` now sets `PatientIndex.guid` equal to the FHIR resource
        id, and the premise is gone on purpose.

        The dual lookup STAYS, because the 150 patients already in production
        each carry two different ids and will until they are regenerated. It
        is a compatibility path for the legacy population, not the design.
        """
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        assert str(p.guid) == str(p.resource_id), (
            "a newly created patient should carry ONE identifier")

    def test_lookup_by_the_platform_guid_still_works(self, client, db):
        """Additive: what matched before must still match, and first."""
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        r = client.get("/api/v1/patients/%s/clinics" % p.guid)
        assert r.status_code == 200
        assert [x["name"] for x in r.get_json()] == [c.name]

    def test_lookup_by_the_fhir_resource_id_now_works(self, client, db):
        """The case that used to 404."""
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        r = client.get("/api/v1/patients/%s/clinics" % p.resource_id)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert [x["name"] for x in r.get_json()] == [c.name]

    def test_an_unknown_value_is_still_404(self, client, db):
        """Accepting a second key must not make the endpoint accept anything."""
        assert client.get(
            "/api/v1/patients/%s/clinics" % uuid.uuid4()).status_code == 404

    def test_a_non_uuid_value_does_not_500(self, client, db):
        """`guid` is a UUID column: a non-UUID must never reach that filter.

        It would raise at the driver and surface as 500 — the #805 shape. A
        non-UUID is a legitimate `resource_id` candidate, so it is looked up
        there instead and simply does not match.
        """
        r = client.get("/api/v1/patients/not-a-uuid-at-all/clinics")
        assert r.status_code == 404, (
            "expected a clean 404, got %s — the UUID column was probably "
            "queried with a non-UUID" % r.status_code)


class TestEuipsEndpointsAcceptEitherIdentifier:
    """The same dual-identifier fix as /clinics, for the two euIPS reads.

    Both did `filter_by(guid=guid)`, so a caller holding the FHIR resource_id
    got 404 for a patient that exists. request.pdhc's patient pages are built
    on that id, so the euIPS section coverage and document header were
    unreachable from the page that most wants to show them.
    """

    def test_sections_by_resource_id(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        r = client.get("/api/v1/patients/%s/euips-sections" % p.resource_id)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["patient_guid"] == str(p.guid), (
            "the response must identify the patient by the PLATFORM guid, "
            "whichever key was used to find them")

    def test_header_by_resource_id(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        r = client.get("/api/v1/patients/%s/euips-header" % p.resource_id)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["patient_guid"] == str(p.guid)

    def test_both_still_work_by_platform_guid(self, client, db):
        c = _clinic(db)
        p = _patient(db, c, managing_org=c.organisation_guid)
        for path in ("euips-sections", "euips-header"):
            assert client.get(
                "/api/v1/patients/%s/%s" % (p.guid, path)).status_code == 200

    def test_a_malformed_guid_is_still_400_on_both(self, client, db):
        """The early guard stays: these two answer 400, not 404, for garbage."""
        for path in ("euips-sections", "euips-header"):
            assert client.get(
                "/api/v1/patients/not-a-uuid/%s" % path).status_code == 400
