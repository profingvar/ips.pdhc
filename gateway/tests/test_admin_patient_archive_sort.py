"""#811 — the admin patient list: sortable headers, archive, batch inspect.

Three things the operator asked for, and one thing they did not ask for but
which decides whether the first three are safe:

* sortable column headers, defaulting to creation date
* an Archive button beside View that hides a row WITHOUT deleting it and
  WITHOUT costing searchability
* a way to see which patients a generation batch created

The fourth is the constraint. `patient_index` already has an `is_active`
boolean that looks exactly like an archive flag, and it is already filtered by
`GET /api/v1/clinics/<guid>/patients` — the roster sim.pdhc builds cohorts
from. Reusing it would have made "archive" silently mean "remove from every
org-scoped roster and stop receiving generated data". So the tests below assert
not only that archiving hides the row but that it changes nothing else, and the
roster test is the one that would have caught the shortcut.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.base import db as _db
from app.models.audit_log import AuditLog
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment


def _seed_patient(db, family="Test", given="Patient", *, identifier=None,
                  birth_date=None, created_at=None, batch=None):
    resource_id = str(uuid.uuid4())
    res = FhirResource(
        resource_type="Patient",
        resource_id=resource_id,
        resource_json={"resourceType": "Patient", "id": resource_id,
                       "name": [{"family": family}]},
    )
    db.session.add(res)
    db.session.flush()
    pi = PatientIndex(
        fhir_resource_guid=res.guid,
        resource_id=resource_id,
        family_name=family,
        given_name=given,
        identifier_value=identifier,
        birth_date=birth_date,
        generation_batch_guid=batch,
    )
    db.session.add(pi)
    db.session.flush()
    if created_at is not None:
        pi.created_at = created_at
        db.session.flush()
    return pi


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def test_default_order_is_newest_first(client, db):
    """Default was family_name, which buries a cohort just generated somewhere
    in the middle of the alphabet. Creation date, descending.

    THREE patients, with names deliberately out of step with their creation
    order. Two would not do: with "Aaronsson" old and "Zetterberg" new, name-
    descending and created-descending produce the same sequence, so the test
    passes against the old behaviour and proves nothing. Verified by reverting
    the default — this version goes red, the two-patient version did not.

        created desc -> Charlie, Alpha, Bravo   <- the only order that satisfies
        name asc     -> Alpha, Bravo, Charlie      both assertions below
        name desc    -> Charlie, Bravo, Alpha
    """
    now = datetime.now(timezone.utc)
    _seed_patient(db, family="Bravo", created_at=now - timedelta(days=10))
    _seed_patient(db, family="Alpha", created_at=now - timedelta(days=5))
    _seed_patient(db, family="Charlie", created_at=now)
    db.session.commit()

    body = client.get("/admin/patients").get_data(as_text=True)
    assert body.index("Charlie") < body.index("Alpha"), (
        "not ordered newest-first")
    assert body.index("Alpha") < body.index("Bravo"), (
        "ordered by name, not by creation date")


def test_name_sort_reverses_on_second_click(client, db):
    _seed_patient(db, family="Aaronsson")
    _seed_patient(db, family="Zetterberg")
    db.session.commit()

    asc = client.get("/admin/patients?sort=name&dir=asc").get_data(as_text=True)
    assert asc.index("Aaronsson") < asc.index("Zetterberg")

    desc = client.get("/admin/patients?sort=name&dir=desc").get_data(as_text=True)
    assert desc.index("Zetterberg") < desc.index("Aaronsson")


def test_no_offered_sort_breaks_the_page(client, db):
    """A smoke across the allowlist, both directions. It asserts only that the
    page renders — the order itself is asserted by the two tests above, for
    `name` and `created`."""
    from app.admin import PATIENT_SORTS
    _seed_patient(db, family="Berg", identifier="19610115-9638",
                  birth_date=date(1961, 1, 15))
    _seed_patient(db, family="Alm", identifier="19720203-1234",
                  birth_date=date(1972, 2, 3))
    db.session.commit()

    for key in PATIENT_SORTS:
        for direction in ("asc", "desc"):
            r = client.get(f"/admin/patients?sort={key}&dir={direction}")
            assert r.status_code == 200, f"{key}/{direction} broke the page"


def test_an_unknown_sort_key_falls_back_and_does_not_500(client, db):
    """The sort key comes from the query string. `getattr(PatientIndex, key)`
    would reach any attribute on the model; the allowlist is why this is a
    200 and not a 500."""
    _seed_patient(db)
    db.session.commit()
    for bad in ("passwOrd", "__class__", "metadata", "' OR 1=1--"):
        r = client.get("/admin/patients", query_string={"sort": bad})
        assert r.status_code == 200, f"sort={bad!r} broke the page"


def test_computed_columns_offer_no_sort_header(client, db):
    """Organisation, Cards and Resources are computed per row AFTER the query,
    so there is nothing to ORDER BY. Offering those headers would sort only
    the fetched page and present it as the whole list."""
    from app.admin import PATIENT_SORTS
    assert "organisation" not in PATIENT_SORTS
    assert "cards" not in PATIENT_SORTS
    assert "resources" not in PATIENT_SORTS


# ---------------------------------------------------------------------------
# Archive — and what it must NOT do
# ---------------------------------------------------------------------------

def _listed(client, guid, **qs) -> bool:
    """Is this patient's ROW in the table?

    Checks for the row's View link rather than for the name anywhere on the
    page: the flash message after archiving quotes the patient's name, so a
    bare "name not in body" check passes for the wrong reason on the redirect
    that follows and fails for the wrong reason here.
    """
    body = client.get("/admin/patients", query_string=qs).get_data(as_text=True)
    return f'href="/admin/patients/{guid}"' in body


def test_archive_hides_from_the_list_but_keeps_the_row(client, db):
    p = _seed_patient(db, family="Hiddensson")
    db.session.commit()
    guid = p.guid

    assert _listed(client, guid)

    r = client.post(f"/admin/patients/{guid}/archive")
    assert r.status_code in (302, 303)

    assert not _listed(client, guid)
    # Not a delete.
    assert _db.session.get(PatientIndex, guid) is not None
    assert _db.session.get(PatientIndex, guid).archived_at is not None


def test_an_archived_patient_is_STILL_SEARCHABLE(client, db):
    """"Do not delete, retain searchability etc but do not list it." A search
    that cannot find an archived patient has lost the record in practice even
    though the row is still there."""
    p = _seed_patient(db, family="Findmesson", identifier="19610115-9638")
    db.session.commit()
    client.post(f"/admin/patients/{p.guid}/archive")

    by_name = client.get("/admin/patients?q=Findmesson").get_data(as_text=True)
    assert "Findmesson" in by_name, "archiving destroyed searchability by name"
    assert "archived" in by_name, "the search hit does not say it is archived"

    by_id = client.get("/admin/patients?q=19610115").get_data(as_text=True)
    assert "Findmesson" in by_id, "archiving destroyed search by identifier"


def test_archive_does_NOT_touch_the_cross_service_clinic_roster(client, db):
    """THE constraint on this feature.

    `patient_index.is_active` is already filtered by
    GET /api/v1/clinics/<guid>/patients, which is the roster sim.pdhc builds
    cohorts from. Had archiving reused that flag — and it looks made for it —
    archiving a row in an admin table would silently have removed the patient
    from every org-scoped roster and stopped them receiving generated data.

    This test fails if anyone later "simplifies" archived_at into is_active.
    """
    clinic = Clinic(name="Roster Clinic", organisation_guid=str(uuid.uuid4()))
    db.session.add(clinic)
    db.session.flush()
    p = _seed_patient(db, family="Rostersson")
    db.session.add(PatientClinicAssignment(patient_guid=p.guid,
                                           clinic_guid=clinic.guid))
    db.session.commit()
    guid, clinic_guid = p.guid, clinic.guid

    client.post(f"/admin/patients/{guid}/archive")

    row = _db.session.get(PatientIndex, guid)
    assert row.is_active is True, (
        "archiving flipped is_active — that flag gates the cross-service "
        "clinic roster, so this would drop the patient from sim's cohorts")
    assert row.archived_at is not None

    # And the assignment itself survives, so the roster query still matches.
    assert (_db.session.query(PatientClinicAssignment)
            .filter_by(patient_guid=guid, clinic_guid=clinic_guid)
            .count() == 1)


def test_archive_is_reversible(client, db):
    p = _seed_patient(db, family="Backagainsson")
    db.session.commit()
    guid = p.guid

    client.post(f"/admin/patients/{guid}/archive")
    assert not _listed(client, guid)

    client.post(f"/admin/patients/{guid}/unarchive")
    assert _listed(client, guid)
    assert _db.session.get(PatientIndex, guid).archived_at is None


def test_the_archived_view_lists_only_archived(client, db):
    kept = _seed_patient(db, family="Keptsson")
    gone = _seed_patient(db, family="Gonesson")
    db.session.commit()
    client.post(f"/admin/patients/{gone.guid}/archive")

    assert _listed(client, gone.guid, archived="1")
    assert not _listed(client, kept.guid, archived="1")


def test_archiving_is_audited_AND_THE_ENTRY_IS_COMMITTED(client, db):
    """Rule 24. Hiding a row from a list is still an operator action on a
    patient record, and "where did that patient go" must be answerable from
    the audit log.

    The `rollback()` is the whole test. `log_event` does `add` + `flush` and
    leaves the commit to its caller. The first version of this feature
    committed the patient change and called `log_event` afterwards, so the
    audit row was flushed into a transaction nobody committed and discarded
    when the request ended — the archive landed in production and the audit
    entry did not. This suite passed anyway, because the fixture's session
    keeps a flushed row visible to the next query in the same session.

    Rolling back first discards anything merely flushed, so only a genuinely
    committed row survives to be counted. Verified: swapping the commit back
    to before `log_event` turns this red.
    """
    p = _seed_patient(db)
    db.session.commit()
    guid = p.guid

    client.post(f"/admin/patients/{guid}/archive")
    _db.session.rollback()
    assert (_db.session.query(AuditLog)
            .filter_by(event_type="patient_archive", patient_guid=guid)
            .count() == 1), "the archive audit entry was never committed"

    client.post(f"/admin/patients/{guid}/unarchive")
    _db.session.rollback()
    assert (_db.session.query(AuditLog)
            .filter_by(event_type="patient_unarchive", patient_guid=guid)
            .count() == 1), "the unarchive audit entry was never committed"

    # And the state change itself survived the same rollback.
    assert _db.session.get(PatientIndex, guid).archived_at is None


def test_archive_is_not_reachable_by_GET(client, db):
    """A GET that writes is followed by crawlers and browser prefetch."""
    p = _seed_patient(db)
    db.session.commit()
    r = client.get(f"/admin/patients/{p.guid}/archive")
    assert r.status_code == 405
    assert _db.session.get(PatientIndex, p.guid).archived_at is None


def test_archiving_an_unknown_patient_404s(client, db):
    r = client.post(f"/admin/patients/{uuid.uuid4()}/archive")
    assert r.status_code == 404


def test_archive_returns_to_the_view_it_was_used_from(client, db):
    """Archiving from a sorted or filtered view and landing on page one of the
    default order loses the operator's place."""
    p = _seed_patient(db, family="Contextsson")
    db.session.commit()
    r = client.post(f"/admin/patients/{p.guid}/archive",
                    data={"sort": "name", "dir": "asc", "q": "Context"})
    assert r.status_code in (302, 303)
    loc = r.headers["Location"]
    assert "sort=name" in loc and "dir=asc" in loc and "q=Context" in loc


# ---------------------------------------------------------------------------
# Batch inspection
# ---------------------------------------------------------------------------

def test_a_batch_can_be_inspected(client, db):
    """"the generated batches — are those patients in the list or how can I
    inspect them?" They ARE in the list and indistinguishable from the rest;
    this filter is how you see which ones a batch created."""
    batch = uuid.uuid4()
    _seed_patient(db, family="Inbatchsson", batch=batch)
    _seed_patient(db, family="Notinbatchsson")
    db.session.commit()

    body = client.get(f"/admin/patients?batch={batch}").get_data(as_text=True)
    assert "Inbatchsson" in body
    assert "Notinbatchsson" not in body


def test_a_malformed_batch_guid_does_not_return_the_WHOLE_LIST(client, db):
    """The dangerous failure mode: a filter that silently does not apply shows
    every patient under a heading saying it is showing one batch."""
    _seed_patient(db, family="Shouldnotappearsson")
    db.session.commit()

    r = client.get("/admin/patients?batch=not-a-guid")
    assert r.status_code == 200
    assert "Shouldnotappearsson" not in r.get_data(as_text=True), (
        "a malformed batch guid fell through to the unfiltered list")


def test_the_batches_card_links_to_the_inspect_view(client, db):
    batch = uuid.uuid4()
    _seed_patient(db, family="Linkedsson", batch=batch)
    db.session.commit()
    body = client.get("/admin/patients").get_data(as_text=True)
    assert f"batch={batch}" in body, "the batch row offers no way to inspect it"


def test_the_page_says_purge_is_permanent_and_not_archive(client, db):
    """The two buttons now sit on the same page and one of them is
    irreversible. The page has to distinguish them in words, not only by
    colour."""
    _seed_patient(db, family="Purgeadjacentsson", batch=uuid.uuid4())
    db.session.commit()
    body = client.get("/admin/patients").get_data(as_text=True)
    assert "permanent delete" in body.lower()
    assert "no undo" in body.lower()
    assert "cdr_6" in body, (
        "the page does not warn that purging leaves downstream observations "
        "pointing at patients that no longer exist")
