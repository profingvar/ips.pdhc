"""#789 + #790 — the mock generator: valid identifiers, and the UI moved.

These go through the real endpoints rather than the helper, because the defect
was in the generator's own line and because "moved the form" is two assertions:
present on the destination AND absent from the origin. Checking only the
destination would let a duplicate survive on both pages, which is the usual way
a "move" turns into a copy.
"""
from __future__ import annotations

from app.models.base import db as _db
from app.models.clinic import Clinic
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import personnummer as pnr


def _clinic(db, name="Test Vårdenhet"):
    c = Clinic(name=name, organisation_guid="org-guid-0001",
               identifier="org-guid-0001", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


class TestGeneratedIdentifiers:
    def test_every_generated_personnummer_is_valid(self, client, db):
        """Before #789 this produced 15-character values whose check digit was
        valid about 10% of the time."""
        c = _clinic(db)
        resp = client.post("/admin/mock-data",
                           data={"clinic_guid": str(c.guid), "count": "25"},
                           follow_redirects=True)
        assert resp.status_code == 200

        patients = _db.session.query(PatientIndex).all()
        assert len(patients) >= 25, f"only {len(patients)} created"

        bad = []
        for p in patients:
            if p.identifier_system != pnr.PERSONNUMMER_SYSTEM:
                continue
            why = pnr.describe_invalid(p.identifier_value, birth=p.birth_date)
            if why:
                bad.append((p.identifier_value, why))
        assert bad == [], f"{len(bad)} invalid, e.g. {bad[:3]}"

    def test_the_length_is_13_not_15(self, client, db):
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "10"},
                    follow_redirects=True)
        lengths = {len(p.identifier_value)
                   for p in _db.session.query(PatientIndex).all()
                   if p.identifier_value}
        assert lengths == {13}, f"lengths seen: {lengths}"

    def test_no_identifier_claims_a_century_its_birth_date_denies(self, client, db):
        """The self-contradictory case: the identifier's encoded birth date
        must equal the row's birth_date. Four live rows fail this."""
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "40"},
                    follow_redirects=True)
        mismatched = []
        for p in _db.session.query(PatientIndex).all():
            if not p.identifier_value or not p.birth_date:
                continue
            encoded = p.identifier_value[:8]
            actual = p.birth_date.strftime("%Y%m%d")
            if encoded != actual:
                mismatched.append((p.identifier_value, actual))
        assert mismatched == [], f"{len(mismatched)} mismatched, e.g. {mismatched[:3]}"

    def test_the_identifier_in_the_fhir_resource_matches_the_index(self, client, db):
        """Two places hold the identifier -- the PatientIndex column and the
        Patient resource JSON. If the generator writes them from different
        expressions they can drift, which is the #768 shape."""
        c = _clinic(db)
        client.post("/admin/mock-data",
                    data={"clinic_guid": str(c.guid), "count": "10"},
                    follow_redirects=True)
        for p in _db.session.query(PatientIndex).all():
            rj = p.fhir_resource.resource_json
            ids = rj.get("identifier") or []
            assert ids, f"patient {p.guid} has no identifier in resource_json"
            assert ids[0]["value"] == p.identifier_value
            assert ids[0]["system"] == p.identifier_system


class TestTheAdminCreateForm:
    def test_a_short_form_personnummer_is_normalised(self, client, db):
        c = _clinic(db)
        client.post("/admin/patients/create",
                    data={"family_name": "Normal", "given_name": "Form",
                          "birth_date": "1961-10-15",
                          "identifier": "6110159638",
                          "clinic_guid": str(c.guid)},
                    follow_redirects=True)
        p = _db.session.query(PatientIndex).filter_by(family_name="Normal").first()
        assert p is not None
        assert p.identifier_value == "19611015-9638"

    def test_a_bad_personnummer_warns_but_still_saves(self, client, db):
        """Deliberate: an operator may be recording a real patient whose
        details are imperfect, and refusing the save would discard the rest of
        the record. The warning is the product, not a rejection."""
        c = _clinic(db)
        resp = client.post("/admin/patients/create",
                           data={"family_name": "Warned", "given_name": "Still",
                                 "birth_date": "1961-10-15",
                                 "identifier": "19611015-0000",
                                 "clinic_guid": str(c.guid)},
                           follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "personnummer looks wrong" in body, body[:400]
        assert _db.session.query(PatientIndex).filter_by(
            family_name="Warned").first() is not None

    def test_junk_in_the_identifier_field_does_not_500(self, client, db):
        """The warning path runs describe_invalid on operator input, so it must
        survive anything typed into it."""
        c = _clinic(db)
        for junk in ("abc", "1234", "....", "19611015_9638"):
            resp = client.post("/admin/patients/create",
                               data={"family_name": f"J{junk[:2]}",
                                     "given_name": "Junk",
                                     "identifier": junk,
                                     "clinic_guid": str(c.guid)},
                               follow_redirects=True)
            assert resp.status_code == 200, f"{junk!r} produced {resp.status_code}"


class TestTheGeneratorMoved:
    """#790. Two assertions, because a move is not just an arrival."""

    def test_it_is_on_the_patients_page(self, client, db):
        _clinic(db)
        body = client.get("/admin/patients").data.decode()
        assert "Generate Mock Patients" in body
        assert "/admin/mock-data" in body
        assert 'name="skip_clinical"' in body

    def test_it_is_gone_from_the_dashboard(self, client, db):
        body = client.get("/admin/").data.decode()
        assert "Generate Mock Patients" not in body
        assert "/admin/mock-data" not in body

    def test_the_organisation_select_is_populated_on_the_new_page(self, client, db):
        """The select used `orgs`, which only the dashboard view passed.
        Moving the markup alone would have rendered 'No organisations'.

        Scoped to the GENERATOR form. The first version asserted
        `"Akademiska" in body`, which passed against the untouched tree
        because the Create Patient form on this page already lists clinics --
        it matched the wrong form and proved nothing. Slice from the
        generator's own form tag instead.
        """
        _clinic(db, name="Akademiska")
        body = client.get("/admin/patients").data.decode()
        i = body.index('action="/admin/mock-data"')
        form = body[i:body.index("</form>", i)]
        assert "Akademiska" in form, form[:600]
        assert "No organisations" not in form
        assert 'id="clinic_select"' in form

    def test_the_empty_state_no_longer_points_at_the_dashboard(self, client, db):
        body = client.get("/admin/patients").data.decode()
        assert "on the dashboard" not in body

    def test_the_post_target_and_field_names_are_unchanged(self, client, db):
        """A relocation, not a redesign: anything already posting here works."""
        c = _clinic(db)
        resp = client.post("/admin/mock-data",
                           data={"clinic_guid": str(c.guid), "count": "2",
                                 "skip_clinical": "on"},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert _db.session.query(PatientIndex).count() == 2
