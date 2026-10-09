"""#805: a malformed clinic guid must be 400, never 500.

`Clinic.guid` is a real UUID column, so `filter_by(guid=<non-uuid>)` RAISES at
the driver and Flask returns 500 — before the route's own 404 branch can run.
The 404 was unreachable for exactly the inputs it was written for.

Found when request.pdhc's new org-scoped patient list probed an unknown clinic
and got a 500 where a 404 was meant. Third occurrence of the same shape: #730
(`analysis_filter` 500ed on one bad guid in a cohort, and cdr turned that into
a reported sibling outage), #791 (hoisted the helper), now these four routes.

400 and 404 are different answers and both matter: 404 says "no such clinic",
400 says "that is not an identifier". A consumer can act on either; it can act
on neither a 500 nor a silence.
"""
import uuid

import pytest

from app.models.clinic import Clinic
from app.services.guids import is_uuid


MALFORMED = ["not-a-uuid", "12345", "", "../../etc/passwd",
             "7f003d04-GGGG-4fdb-bf5f-4a28cccbe0a7"]


def _clinic(db):
    c = Clinic(name="Guard Test", organisation_guid="org-guard-1",
               identifier="org-guard-1", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


class TestTheHelper:
    def test_it_is_total(self):
        """Every caller is guarding a query and wants a verdict, so nothing
        unparseable may raise."""
        for bad in MALFORMED + [None, 0, [], {}]:
            assert is_uuid(bad) is False, repr(bad)

    def test_a_real_uuid_passes(self):
        assert is_uuid(str(uuid.uuid4())) is True
        assert is_uuid(uuid.uuid4()) is True

    def test_there_is_only_ONE_definition(self):
        """#791's lesson, kept. `patient_routes._is_uuid` must BE this
        function, not a copy of it — two definitions of one rule is the shape
        that cost #784 and #786 a day each."""
        from app.api.patient_routes import _is_uuid
        assert _is_uuid is is_uuid


class TestAllFourClinicRoutes:
    @pytest.mark.parametrize("bad", MALFORMED)
    def test_GET_clinic_is_400(self, client, db, bad):
        r = client.get("/api/v1/clinics/%s" % bad)
        assert r.status_code in (400, 404, 405), r.status_code
        if r.status_code == 400:
            assert "malformed" in r.get_data(as_text=True).lower()
        assert r.status_code != 500

    @pytest.mark.parametrize("bad", MALFORMED)
    def test_GET_clinic_patients_is_400(self, client, db, bad):
        r = client.get("/api/v1/clinics/%s/patients" % bad)
        assert r.status_code != 500, "a malformed guid reached the UUID column"
        if r.status_code == 400:
            assert "malformed" in r.get_data(as_text=True).lower()

    def test_PATCH_clinic_is_400(self, client, db):
        r = client.patch("/api/v1/clinics/not-a-uuid", json={"name": "x"})
        assert r.status_code != 500
        assert r.status_code == 400

    def test_POST_clinic_patient_is_400(self, client, db):
        r = client.post("/api/v1/clinics/not-a-uuid/patients",
                        json={"family_name": "X", "given_name": "Y",
                              "birth_date": "1980-01-01", "gender": "other"})
        assert r.status_code != 500
        assert r.status_code == 400


class TestTheRealAnswersStillWork:
    """A guard that also broke the valid cases would be no improvement."""

    def test_a_WELL_FORMED_unknown_guid_is_still_404(self, client, db):
        """The distinction the fix exists to preserve."""
        r = client.get("/api/v1/clinics/%s" % uuid.uuid4())
        assert r.status_code == 404
        assert "not found" in r.get_data(as_text=True).lower()

    def test_a_real_clinic_still_resolves(self, client, db):
        c = _clinic(db)
        r = client.get("/api/v1/clinics/%s" % c.guid)
        assert r.status_code == 200
        assert r.get_json()["name"] == "Guard Test"

    def test_its_patients_list_still_resolves(self, client, db):
        c = _clinic(db)
        r = client.get("/api/v1/clinics/%s/patients" % c.guid)
        assert r.status_code == 200
        assert r.get_json() == []
