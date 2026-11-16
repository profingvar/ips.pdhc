"""#870 found in ips: UCUM quantities without a code get one, as a new version."""
from __future__ import annotations

import pathlib
import sys
import uuid

import pytest

from app.models.fhir_resource import FhirResource
from app.services import ucum_code_backfill as mig

U = "http://unitsofmeasure.org"


def _obs(unit, code=None, system=U):
    q = {"value": 1, "unit": unit, "system": system}
    if code:
        q["code"] = code
    return {"resourceType": "Observation", "status": "final", "valueQuantity": q}


@pytest.mark.parametrize("text,code", [("mmHg", "mm[Hg]"), ("mL/min/1.73m2", "mL/min/{1.73_m2}"), ("kg", "kg")])
def test_the_code_is_MAPPED(text, code):
    new, ch = mig.migrate_resource_json("Observation", _obs(text))
    assert new["valueQuantity"]["code"] == code and new["valueQuantity"]["unit"] == text
    assert ch == [f"code:{text}->{code}"]


def test_components_too():
    j = {"resourceType": "Observation", "component": [{"valueQuantity": {"unit": "mmHg", "system": U}}]}
    new, _ = mig.migrate_resource_json("Observation", j)
    assert new["component"][0]["valueQuantity"]["code"] == "mm[Hg]"


@pytest.mark.parametrize("j", [_obs("kg", "kg"), _obs("kg", system="http://other"), _obs("weird")])
def test_untouched(j):
    assert mig.migrate_resource_json("Observation", j) == (j, [])


def test_input_not_mutated():
    j = _obs("mmHg"); snap = repr(j)
    mig.migrate_resource_json("Observation", j)
    assert repr(j) == snap


def test_every_mapping_target_is_valid_UCUM():
    tb = pathlib.Path(__file__).resolve().parents[3] / "termbank.pdhc"
    if not (tb / "app" / "ucum" / "ucum-essence.xml").exists():
        pytest.skip("termbank checkout not beside ips")
    sys.path.insert(0, str(tb / "app"))
    try:
        import ucum  # termbank's validator, loaded as a plain package
        bad = [c for c in set(mig.TEXT_TO_UCUM.values()) if not ucum.is_valid(c)]
        assert not bad, bad
    finally:
        sys.path.remove(str(tb / "app"))
        sys.modules.pop("ucum", None)


class TestTheCli:
    @pytest.fixture
    def seeded(self, client, db):
        rows = [FhirResource(resource_type="Observation", resource_id=str(uuid.uuid4()), version_id=1,
                             status="active", patient_guid=uuid.uuid4(), resource_json=j)
                for j in (_obs("mmHg"), _obs("kg"), _obs("kg", "kg"))]
        db.session.add_all(rows); db.session.commit()
        return rows

    def _run(self, client, *a):
        return client.application.test_cli_runner().invoke(args=["backfill-ucum-codes", *a])

    def test_dry_run_then_apply_writes_versions(self, client, db, seeded):
        assert "2 would change" in self._run(client).output
        assert db.session.query(FhirResource).filter_by(status="superseded").count() == 0
        out = self._run(client, "--apply", "--expect", "2").output
        assert "wrote 2 new version(s)" in out, out
        db.session.expire_all()
        v = {r.version_id: r for r in db.session.query(FhirResource).filter_by(resource_id=seeded[0].resource_id)}
        assert "code" not in v[1].resource_json["valueQuantity"] and v[1].status == "superseded"
        assert v[2].resource_json["valueQuantity"]["code"] == "mm[Hg]"
        assert "0 would change" in self._run(client).output

    def test_an_unmapped_text_aborts_everything(self, client, db, seeded):
        db.session.add(FhirResource(resource_type="Observation", resource_id=str(uuid.uuid4()), version_id=1,
                                    status="active", patient_guid=uuid.uuid4(), resource_json=_obs("furlongs")))
        db.session.commit()
        res = self._run(client, "--apply")
        assert res.exit_code != 0 and "furlongs" in str(res.exception or res.output)
        assert db.session.query(FhirResource).filter_by(status="superseded").count() == 0
