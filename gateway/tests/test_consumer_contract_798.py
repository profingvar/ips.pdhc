"""#798 — pin the endpoints and response shapes sibling services actually read.

The operator's binding constraint on the whole euIPS reform is "do not lose any
of the functionality in the present setup". This is how that is checked rather
than hoped for.

## The consumer map, corrected

#788's epic table was built by grepping endpoint PATHS without distinguishing
the target host, and it was wrong in one important way: it listed
`/api/v1/fhir/Patient`, `/fhir/Observation` and `/fhir/Condition` as ips
endpoints with four consumers. **ips has no `/api/v1/fhir/*` routes at all** —
confirmed against the live URL map. Those paths exist on the CDRs, which expose
an identical FHIR surface, and that is what analyse, dashboard, cdr and gateway
read.

That matters beyond tidiness: the ticket asked for a test that an
absent/unknown resource from #793 does not break `/fhir/Condition` for "the
four services that read them". **No service reads those from ips**, so the risk
does not exist and a test for it would have been theatre.

What siblings REALLY call, extracted from their call sites and verified against
the live URL map:

| endpoint | consumers |
|---|---|
| `POST /api/v1/patients/analysis-filter` | cdr, cdr_6, analyse, dashboard, rosetta |
| `GET /api/v1/patients/<guid>/blocks` | analyse, dashboard, cdr_6, gateway |
| `GET /api/v1/patients/<guid>/blocks/check` | request, analyse |
| `GET /api/v1/patients/<guid>/blocks/metadata` | analyse |
| `GET /api/v1/patients/<guid>/clinics` | request — the #779 gate |
| `GET /api/v1/patients/<guid>/consents/check` | request |
| `GET /api/v1/patients/<guid>/consents` | contract |
| `GET /api/v1/clinics`, `/api/v1/clinics/<guid>/patients` | sim |
| `GET /api/v1/health` | sim |

Two more paths were found and are NOT live calls: analyse's
`/api/v1/observations/search` goes to a CDR node, not ips, and
`/api/v1/blocks/check-bulk` appears only in a comment about a call #717
retired.

One IS live and broken — `contract.pdhc` GETs `/api/v1/patients/<guid>`, which
does not exist. Recorded in its own ticket; this file pins the shapes that DO
work so the reform cannot quietly change them.
"""
from __future__ import annotations

import uuid

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment


def _patient(db, clinic=None, **kw):
    rid = str(uuid.uuid4())
    res = FhirResource(resource_type="Patient", resource_id=rid,
                       resource_json={"resourceType": "Patient", "id": rid})
    db.session.add(res)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=res.guid, resource_id=rid,
                     family_name="Contract", given_name="Test", **kw)
    db.session.add(p)
    db.session.commit()
    res.patient_guid = p.guid
    if clinic:
        db.session.add(PatientClinicAssignment(patient_guid=p.guid,
                                               clinic_guid=clinic.guid))
    db.session.commit()
    return p


def _clinic(db, name="Contract Clinic", org="org-contract-0001"):
    c = Clinic(name=name, organisation_guid=org, identifier=org, is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


class TestTheRoutesConsumersCallAllExist:
    """A missing route is the defect contract.pdhc is living with right now, so
    existence is pinned separately from shape."""

    def test_every_consumed_route_is_registered(self, app):
        rules = {str(r) for r in app.url_map.iter_rules()}
        required = {
            "/api/v1/patients/analysis-filter",
            "/api/v1/patients/<patient_guid>/blocks",
            "/api/v1/patients/<patient_guid>/blocks/check",
            "/api/v1/patients/<patient_guid>/blocks/metadata",
            "/api/v1/patients/<guid>/clinics",
            "/api/v1/patients/<patient_guid>/consents",
            "/api/v1/patients/<patient_guid>/consents/check",
            "/api/v1/clinics",
            "/api/v1/clinics/<guid>/patients",
            "/api/v1/health",
        }
        missing = sorted(required - rules)
        assert missing == [], f"consumed routes no longer registered: {missing}"

    def test_ips_has_no_fhir_surface_and_nothing_expects_one(self, app):
        """Corrects #788's table. If a `/api/v1/fhir/*` route is ever added
        here, the absent/unknown resources from #793 become visible to whoever
        reads it — so that addition needs its own thought, and this test marks
        the boundary."""
        fhir = [str(r) for r in app.url_map.iter_rules()
                if "/api/v1/fhir" in str(r)]
        assert fhir == [], fhir


class TestTheClinicsShape:
    """`GET /patients/<guid>/clinics` — request.pdhc's #779 gate."""

    def test_guid_and_organisation_guid_are_distinct_fields(self, client, db):
        """#779: conflating these denied EVERY non-SU caller for months,
        because the gate compared sso organisation guids against ips clinic
        guids — two identifier spaces that are never equal."""
        c = _clinic(db)
        p = _patient(db, clinic=c)
        body = client.get(f"/api/v1/patients/{p.guid}/clinics").get_json()
        assert isinstance(body, list) and body
        row = body[0]
        assert "guid" in row and "organisation_guid" in row
        assert row["guid"] != row["organisation_guid"], \
            "guid and organisation_guid must stay distinct identifier spaces"
        assert row["organisation_guid"] == c.organisation_guid

    def test_a_patient_with_no_assignment_returns_an_empty_list(self, client, db):
        """Not 404: request.pdhc distinguishes "no clinics" from "no patient",
        and the refusal reasons differ."""
        p = _patient(db)
        resp = client.get(f"/api/v1/patients/{p.guid}/clinics")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_an_unknown_patient_is_404(self, client, db):
        resp = client.get(f"/api/v1/patients/{uuid.uuid4()}/clinics")
        assert resp.status_code == 404


class TestTheAnalysisFilterShape:
    """Five services depend on this one endpoint."""

    def test_it_returns_allowed_and_excluded_with_reasons(self, client, db):
        p = _patient(db, ehds_opt_out=True)
        body = client.post("/api/v1/patients/analysis-filter",
                           json={"patient_guids": [str(p.guid)],
                                 "purpose": "research"}).get_json()
        assert set(body) >= {"purpose", "allowed", "excluded"}
        assert isinstance(body["allowed"], list)
        assert isinstance(body["excluded"], list)
        assert body["excluded"], "an EHDS opt-out must be excluded"
        assert "reason" in body["excluded"][0]
        assert "patient_guid" in body["excluded"][0]

    def test_a_malformed_guid_is_excluded_not_raised(self, client, db):
        """#730's SECOND defect. PatientIndex.guid is a real Postgres uuid
        column, so an unparseable guid reaching the IN clause raised at the
        driver and this endpoint answered 500 — which cdr turns into
        IpsUnreachable and fail-closes the WHOLE cohort while blaming the wrong
        service. One bad guid denied everything.
        """
        resp = client.post("/api/v1/patients/analysis-filter",
                           json={"patient_guids": ["not-a-uuid"],
                                 "purpose": "research"})
        assert resp.status_code == 200, resp.data[:200]
        body = resp.get_json()
        assert body["allowed"] == []
        assert body["excluded"][0]["reason"] == "malformed_guid"

    def test_one_bad_guid_does_not_deny_the_good_ones(self, client, db):
        """Per-patient fail-closed, not per-request."""
        p = _patient(db)
        body = client.post("/api/v1/patients/analysis-filter",
                           json={"patient_guids": [str(p.guid), "rubbish"],
                                 "purpose": "statistics"}).get_json()
        assert str(p.guid) in body["allowed"]
        assert any(e["reason"] == "malformed_guid" for e in body["excluded"])

    def test_a_missing_purpose_is_400(self, client, db):
        resp = client.post("/api/v1/patients/analysis-filter",
                           json={"patient_guids": []})
        assert resp.status_code == 400


class TestTheClinicPatientsShape:
    """`GET /clinics/<guid>/patients` — sim.pdhc's cohort builder."""

    def test_it_returns_patient_dicts_with_the_keys_sim_reads(self, client, db):
        c = _clinic(db)
        _patient(db, clinic=c)
        body = client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()
        assert isinstance(body, list) and body
        row = body[0]
        for key in ("guid", "identifier_system", "identifier_value",
                    "family_name", "given_name", "birth_date", "gender",
                    "is_active"):
            assert key in row, f"{key} disappeared from the patient dict"

    def test_the_euips_additions_are_additive_only(self, client, db):
        """#791 added generation_batch_guid to this dict. Additive is the rule
        because nine services read this service."""
        c = _clinic(db)
        _patient(db, clinic=c)
        row = client.get(f"/api/v1/clinics/{c.guid}/patients").get_json()[0]
        assert "generation_batch_guid" in row
        assert row["generation_batch_guid"] is None


class TestTheReformIntroducedNoNewRequiredField:
    """The reform must not have made anything mandatory that consumers do not
    send."""

    def test_a_patient_can_still_exist_with_no_batch_and_no_identifier(self, client, db):
        p = _patient(db)
        assert p.generation_batch_guid is None
        assert p.identifier_value is None
        d = p.to_dict()
        assert d["guid"]

    def test_the_patient_guid_is_still_the_join_key(self, client, db):
        """Rule 18. The personnummer is an identifier and never a join key --
        #789 could have been read as promoting it."""
        c = _clinic(db)
        p = _patient(db, clinic=c)
        body = client.get(f"/api/v1/patients/{p.guid}/clinics")
        assert body.status_code == 200
        # And the identifier is NOT accepted in its place.
        assert client.get("/api/v1/patients/19611015-9638/clinics").status_code \
            in (400, 404)
