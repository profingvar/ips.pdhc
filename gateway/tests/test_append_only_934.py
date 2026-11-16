"""#934 — every content change to fhir_resources is a NEW VERSION.

Decision (operator, 2026-11-16): backfills and migrations version, they never
mutate in place. `update_resource` was the model all along and had never run
(0 superseded rows in production); the two writers that changed content went
around it. Now they go through it, the readers that would have tripped over a
second row are fixed, and a guard forbids a direct `resource_json` write.
"""
from __future__ import annotations

import ast
import pathlib
import uuid

from app.models.base import db as _db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_header_backfill as bf
from app.services.fhir_service import create_resource, read_resource, update_resource

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _patient(db, **extra):
    body = {"resourceType": "Patient", "name": [{"family": "Versionsson", "given": ["Ada"]}],
            "birthDate": "1970-01-01", **extra}
    r = create_resource("Patient", body, patient_guid=uuid.uuid4())
    db.session.commit()
    return r


# ----------------------------------------------------------------- update_resource

def test_update_writes_v2_and_supersedes_v1_with_its_content_intact(app, db):
    r = _patient(db)
    rid = r.resource_id
    body = dict(r.resource_json)
    body["language"] = "sv"
    update_resource("Patient", rid, body)
    db.session.commit()
    rows = {x.version_id: x for x in db.session.query(FhirResource).filter_by(resource_id=rid)}
    assert set(rows) == {1, 2}
    assert rows[1].status == "superseded" and "language" not in rows[1].resource_json
    assert rows[2].status == "active" and rows[2].resource_json["language"] == "sv"
    assert rows[2].patient_guid == rows[1].patient_guid
    assert read_resource("Patient", rid).version_id == 2


def test_the_new_version_shares_no_nested_json_with_the_old(app, db):
    r = _patient(db)
    body = r.resource_json            # the caller edits what it just read
    new = update_resource("Patient", r.resource_id, body)
    new.resource_json["name"][0]["family"] = "Changed"
    assert r.resource_json["name"][0]["family"] == "Versionsson"


def test_the_patient_index_follows_the_new_version(app, db):
    r = _patient(db)
    new = update_resource("Patient", r.resource_id, dict(r.resource_json))
    db.session.commit()
    idx = db.session.query(PatientIndex).filter_by(resource_id=r.resource_id).one()
    assert idx.fhir_resource_guid == new.guid


# ----------------------------------------------------------------- the two writers

def test_the_header_backfill_VERSIONS_the_patient(app, db, monkeypatch):
    r = _patient(db)
    monkeypatch.setattr(bf, "plan", lambda limit=None: {"actions": [{
        "patient_guid": r.patient_guid, "skip": False, "needs_related": False,
        "needs_coverage": False, "needs_language": True, "needs_contact_inline": False,
        "family": "Versionsson", "city": "Solna"}]})
    out = bf.run(dry_run=False, seed=934)
    assert out["patched_language"] == 1
    rows = {x.version_id: x for x in db.session.query(FhirResource).filter_by(resource_id=r.resource_id)}
    assert rows[1].status == "superseded" and "language" not in rows[1].resource_json
    assert rows[2].status == "active" and rows[2].resource_json.get("language")


def test_the_device_migration_examines_ONLY_current_versions(client, db):
    dev = FhirResource(resource_type="Device", resource_id=str(uuid.uuid4()), version_id=1,
                       status="superseded", patient_guid=uuid.uuid4(),
                       resource_json={"resourceType": "Device", "patient": {"reference": "Patient/x"}})
    db.session.add(dev)
    db.session.commit()
    res = client.application.test_cli_runner().invoke(args=["migrate-r5-device-elements"])
    assert "0 would change" in res.output, "a superseded row is history, not a target"


# ----------------------------------------------------------------- readers

def test_implant_existing_returns_the_CURRENT_version(app, db):
    from app.api.implant_routes import _existing
    rid = str(uuid.uuid4())
    v1 = FhirResource(resource_type="Device", resource_id=rid, version_id=1, status="active",
                      resource_json={"resourceType": "Device", "v": 1})
    db.session.add(v1)
    db.session.commit()
    update_resource("Device", rid, {"resourceType": "Device", "v": 2})
    db.session.commit()
    # make v1 the physically-first row a naive .first() would likely return
    assert _existing(rid).resource_json["v"] == 2


def test_a_batch_purge_removes_EVERY_version(client, db):
    from app.services import euips_batch
    from tests.test_batches_797 import _clinic, _generate
    _generate(client, _clinic(db), 2)
    p = _db.session.query(PatientIndex).first()
    fr = _db.session.get(FhirResource, p.fhir_resource_guid)
    rid, batch = fr.resource_id, str(p.generation_batch_guid)
    update_resource("Patient", rid, dict(fr.resource_json))
    _db.session.commit()
    assert _db.session.query(FhirResource).filter_by(resource_id=rid).count() == 2
    euips_batch.purge_batch(batch)
    _db.session.expire_all()
    assert _db.session.query(FhirResource).filter_by(resource_id=rid).count() == 0


# ----------------------------------------------------------------- the guard

def _direct_writes():
    hits = []
    for f in sorted(APP.rglob("*.py")):
        if f.name == "fhir_service.py" or "migrations" in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
            for t in targets:
                if isinstance(t, ast.Attribute) and t.attr == "resource_json":
                    hits.append(f"{f.relative_to(APP)}:{n.lineno}")
    return hits


def test_nobody_writes_resource_json_in_place_outside_fhir_service():
    assert _direct_writes() == [], "use fhir_service.update_resource (#934)"


def test_CONTROL_the_guard_sees_an_assignment(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text("row.resource_json = {}\n")
    import sys
    monkeypatch.setattr(sys.modules[__name__], "APP", tmp_path)
    assert _direct_writes() == ["x.py:1"]
