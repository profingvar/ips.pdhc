
## #792 — euIPS document header (2026-10-08)

Phase B2. `app/services/euips_header.py` + `euips_header_backfill.py`,
`GET /api/v1/patients/<guid>/euips-header`, wired into `ips_generator` and the
mock generator. DEPLOYED.

### The watch item drove the design

#792 flags that the Composition custodian, the Patient's
`managingOrganization` and the `PatientClinicAssignment` row are three places
holding ONE organisation — the #768 shape, where three organisation
identifiers on one datapoint failed to collapse and a Rule 24 gate scoped on
the wrong org.

**THE ASSIGNMENT IS AUTHORITATIVE.** `_custodian_clinic` reads it from
`PatientClinicAssignment` — what cross-service consumers actually query, since
`/api/v1/clinics/<guid>/patients` joins on that table and not on
`managingOrganization` — and custodian, author and attester are projections of
it. A stale `managingOrganization` does not win, and is not swallowed either:
`custodian_disagreement` surfaces it as a bundle `meta.tag` and as
`custodian_mismatch` in the endpoint. #768 happened because a mismatch was
invisible; preferring the right source silently is only half a fix.

No assignment ⇒ no custodian, author or attester. An unattributed document is
correct; an invented attribution is not.

### Decisions a reviewer should push back on if they disagree

- **All three parties are the Organization, not a Practitioner.** A generated
  summary has no human author; naming one would put a clinician who does not
  exist into clinical data, where no later reader could tell the fabrication
  from a real attribution. FHIR permits Organization for `author` and
  `attester.party`.
- **A guardian only for a minor.** An adult may have a *god man*, but that is
  a court appointment, not an inference from age. Unknown age ⇒ no guardian,
  because unknown is not minor. Measured over 3000 draws of the generator's
  1940–2010 birth range: **101 minors, 101 guardians** — the path fires, and
  only there.
- **`Coverage.insurer` is a display-only Reference.** ips holds no region
  registry, so `Organization/<guid>` would point at nothing — the dangling
  reference #771 and #768 are both about. PUBLICPOL regional cover, insurer
  derived from the patient's city so a Stockholm resident is not on Region
  Skåne's books.
- **Country of origin has no FHIR Composition element.** Rather than mint an
  extension URL no validator would recognise, it rides on the custodian
  Organization's and the Patient's `address.country`, and the module says so
  instead of implying a standard exists.

### Unverified and labelled

`CODES_VERIFIED = False`, like `euips_sections`, and the endpoint returns it.
Two R5-vs-R4 shapes are asserted and want a reviewer's eye, because the R4 form
would validate nowhere: `Coverage` uses `kind` + `insurer` (R4: `payor`, no
`kind`), and `Composition.attester.mode` is a CodeableConcept (R4: plain code).
Both have explicit tests.

Header resources are fetched separately from the clinical types so they never
reach `_build_sections` — a "Coverage section" is a section the guideline does
not define.

### Live verification (ips-app-1, real patient 8f83e561…)

```
route registered : ['/api/v1/patients/<guid>/euips-header']
unauthenticated  : 401 Missing Authorization header
assigned clinic  : Test Clinic  org 7f003d04-…
custodian        : urn:uuid:7f003d04-…  display 'Test Clinic'
attester mode    : CodeableConcept, code 'legal'
language         : sv-SE      mismatch: None
guardian         : not_applicable — "patient is an adult, so a guardian
                   would be invented"   (age 68)
RelatedPerson: 0   Coverage: 0
header complete  : False   missing: ['contact_person', 'health_insurance']
```

### The header is half derived, half stored — so the deploy only half fixed it

That last line is the finding. Deriving on read gave **every existing patient**
a correct custodian, author, attester and language the moment the image
restarted. The two STORED resources were absent for all of them, because
nothing had written them.

`flask euips-header-backfill` closes the gap. **DRY RUN BY DEFAULT**, and
deliberately not a migration: it writes statements about real people (a next of
kin, an insurance policy) and these rows feed cdr_6, analyse and every spärr
decision downstream, so manufactured ones would be indistinguishable later from
data a clinician entered. Idempotent; `--seed` makes the dry run and the real
run produce identical values.

Production dry run, 2026-10-08 — **nothing written, awaiting operator go/no-go**:

```
patients examined       : 150
need contact persons    : 150
need health insurance   : 150
need a document language: 150
of which legal guardians: 5   (minors only)
```

618 passed; `tests/test_patient_portal_html.py`'s draft-banner test fails
identically with these changes stashed (pre-existing, unrelated).

### #792 backfill APPLIED — 2026-10-08, operator-authorised

Pre-write snapshot: `miserver:~/backups/predeploy/ips.pdhc/792/ips_20261008T091737Z.pgdump`
(188K, `pg_dump -Fc` of `ips_db`). Taken because the backfill patches 150
existing `Patient.resource_json` rows in place, not only inserts.

Run with `--seed 20261008`, so the dry run and the applied run produced
identical values and the operation is reproducible:

```
patients examined       : 150
created RelatedPerson   : 155     (150 contacts + 5 guardians)
created Coverage        : 150
patched language        : 150
patched Patient.contact : 150
```

Verified afterwards:

| check | result |
|---|---|
| `fhir_resources` Coverage / RelatedPerson | 150 / 155 |
| patients with no contact person | **0** |
| patients with no insurance | **0** |
| guardians created, and their ages | 5 — **[3, 3, 9, 16, 17]** |
| any guardian on an adult or unknown age | **none** |
| language spread | sv-SE 133, en-GB 8, so-SO 4, fi-FI 2, ar 2, fa 1 |
| headers still incomplete | **0** |
| second `--no-dry-run` run | created 0, patched 0 — idempotent |

**The guardian ages are worth noting.** The mock generator only produces
1940–2010 births, so its youngest patient is 16. Ages **3 and 9** are
Synthea-imported patients — the guardian rule is therefore doing real work on
imported data, not just on generated cohorts, and the age gate is what keeps it
from attaching a guardian to the 145 adults.

Endpoint re-check on the same real patient that reported
`missing: ['contact_person','health_insurance']` before the backfill:

```
RelatedPerson    : 1   Coverage: 1
header complete  : True   missing: []
guardian         : not_applicable — "patient is an adult, so a guardian
                   would be invented"   (age 68)
custodian        : urn:uuid:7f003d04-…  'Test Clinic'     mismatch: None
```

So #792 is now complete for the existing population as well as for newly
generated patients.

## 2026-10-08/09 — the operator principle: one guid, personnummer, caregiver + careunit

Operator, 2026-10-08:

> Patient information must be reachable by THE guid wherever it is in the
> platform, and a guid must have a 1:1 relation to a personnummer, a caregiver
> and a careunit. If careunit is not given then the careunit should be set to
> the caregiver.

### Conformance before the work — every patient failed, twice

| rule | before |
|---|---|
| one guid, reachable everywhere | **0 / 150** — every patient carried two |
| 1:1 guid ↔ personnummer | **0 / 150 valid** — all doubled-century |
| 1:1 guid ↔ caregiver + careunit | 122 had one org, **28 had none** |

The personnummer finding is why a wipe became the only honest route: #789's fix
applied to newly generated patients and **none had been generated since**, so
the entire population carried a malformed identifier. A personnummer is an
identity, not a field — recomputing one changes who the record is about.

### What was changed

**Rule 1.** `fhir_service` minted two independent uuid4s for one person:
`PatientIndex.guid` took the column default while `resource_id` came from the
FHIR resource. `PatientIndex.guid` is now set EQUAL to the resource id. The
platform guid stays canonical (#782, the CDRs and §1 of the technical manual
all call it that); a FHIR resource id is free-form by spec, so that is the side
with room to give. A non-UUID resource id cannot be unified — that patient
keeps two ids and the breach is logged, never silently tolerated.

**Rules 2b/3.** `clinics.care_organisation_guid` added (migration
`add_clinic_care_organisation.sql`). ips could not express the two levels at
all before: an assignment recorded ONE unlabelled organisation and the
hierarchy lived only in sso, so every consumer had to call sso to learn which
level it was looking at — and a vårdenhet is the **spärrgräns**, so that is a
legal distinction. `Clinic.to_dict()` now returns `care_unit_guid`,
`care_organisation_guid` and `is_own_caregiver`.

**The operator's fallback is STORED, not recomputed.** Where sso records no
parent, `care_organisation_guid = organisation_guid`. A rule every consumer
re-derives is a rule some consumer gets wrong. NULL is also safe:
`is_own_caregiver()` treats an unsynced row as its own caregiver, the same
fallback, so an unsynced clinic degrades to the correct answer.

`flask sync-care-hierarchy` mirrors sso (dry-run default) and refuses to invent
a caregiver for an organisation sso does not know — #767 and #780 were exactly
that. Applied 2026-10-08 to **11 of 11 clinics, zero unresolved**; only UAS has
a real parent (Region Uppsala), every other organisation is its own caregiver.

**The generator is no longer browser-only.** `generate_mock_data` was ~200
lines inside a route reading `request.form` and reporting via `flash()`, so an
SSO browser session was the only way to run it. Extracted to
`app/services/mock_generator.py`; the route still calls it, and
`flask generate-patients` is the second caller. The CLI REFUSES a clinic it
cannot resolve — unassigned patients are the 28-patient problem this work ends.

### Conformance after — new cohort clean, legacy unchanged

Same measurement script, run again:

```
NEW cohort — UAS, batch 1cea906c   (n=60)
  one guid                 60/60
  valid personnummer       60/60   (invalid 0, duplicated 0)
  both care levels         60/60   (no organisation 0)
  euIPS required sections  60/60

LEGACY cohort                      (n=150)
  one guid                  0/150
  valid personnummer        0/150
  both care levels        122/150   (28 have no organisation)
  euIPS required sections  40/150
```

### Why UAS, and why the legacy 150 stayed

Operator chose **option A**: regenerate alongside rather than wipe.

UAS already existed, held zero patients, and is the platform's ONLY real
vårdenhet with a caregiver above it — so it gives a second populated
organisation *and* the only careunit ≠ caregiver case, making the two-level
display verifiable instead of degenerate. No sso write was needed.

The legacy 150 stayed because **22 of them are referenced by 27
ServiceRequests anchoring all 690 data-exchange grants**, including
CambioCaregiver's 680 and Medituner's 6. `data_exchange_grants
.service_request_guid` is a FK with `NO ACTION`, so Postgres would have refused
the delete. I had recommended deleting those SRs as "records that shouldn't
exist"; that was wrong, and the recommendation was withdrawn before anything
was deleted.

### Org scoping is finally verifiable — and verified

It could not be tested before: every patient sat in one organisation, so a
correct filter and a broken one returned the same rows (the #779 failure mode).
With two populated organisations, through the DEPLOYED request.pdhc code:

```
Test Clinic  org=7f003d04 -> clinic=2cc4e9e1 -> 122 patients
UAS          org=7d55624c -> clinic=02b83b6b ->  60 patients
overlap: 0
UAS-only caller resolving Test Clinic's org: REFUSED
```

Note the org guid and the clinic guid are different values in both rows — that
mapping is the #779 boundary, and it is exercised here rather than asserted.

### Outstanding

- The legacy 150 remain non-conformant by design. They are reachable, they
  serve the two partner integrations, and their state is recorded above rather
  than hidden.
- `test_optional_sections_795`'s advance-directive assertion is flaky:
  directives generate at 0.15 and are skipped for minors, so P(zero in 40) is
  about 0.2%. Observed once, then three clean full runs.

---

## 2026-10-09 — #810 admin patient list: sortable headers, archive, batch inspect

Operator: "Sort it upon click on the header row, default creation date. Add an
archive button beside the view button. Do not delete, retain searchability etc
but do not list it."

### Sorting is SERVER-SIDE, and that is not an implementation detail

The list is capped at 100 rows (`LIST_LIMIT`, unchanged). A client-side sort
would reorder the 100 rows that happened to be fetched and present the result
as "the patients sorted by X" — wrong the moment a 101st patient exists, and
there are 216 in production. So the sort is in the query, driven by header
links, with `PATIENT_SORTS` as an **allowlist**: `getattr(PatientIndex, key)`
on a query-string value would reach any attribute on the model.

Default is now `created` descending, was `family_name`. A cohort that was just
generated was previously buried mid-alphabet.

`Organisation`, `Cards` and `Resources` deliberately get **no** sort header:
all three are computed per row after the query, so there is nothing to ORDER
BY, and a header that silently sorted one page would be worse than no header.

### Archive is a NEW column, not the `is_active` that already exists

`patient_index.is_active` looks made for this. It is not available: it is FHIR
`Patient.active` and it is already filtered by `app/api/clinic_routes.py` on
`GET /api/v1/clinics/<guid>/patients` — the roster **sim.pdhc builds cohorts
from**. Reusing it would have made "archive" silently also mean "remove from
every org-scoped roster and stop receiving generated data".

So `archived_at TIMESTAMPTZ NULL` (migration `add_patient_archived_at.sql`,
applied to prod, idempotent, partial index on the selective direction). A
timestamp rather than a bool answers "archived?" and "when?" in one column.

What archiving does **not** do: it does not delete, does not touch
`is_active`, does not remove the clinic assignment, and does not change a
single API response. An archived patient is still returned by
`GET /api/v1/patients/<guid>` and still appears in its clinic's roster. The
only thing that changes is the default admin list. Searching by name or
identifier still finds them, marked `archived`; `?archived=1` shows them alone.
Archive is a POST (a GET that writes gets followed by prefetch) and carries the
current q/sort/dir/archived/batch so the operator lands back where they were.

### Batch inspection

"are those patients in the list or how can I inspect them?" — they are in the
list, mixed in and indistinguishable. Each batch row now has **Inspect**,
which filters the list by `generation_batch_guid`. A malformed guid returns
nothing rather than falling through to the unfiltered list under a heading
claiming to show one batch.

The batches card now also spells out, in words, that **Purge is a permanent
delete and is not Archive**, including that observations already pushed to
cdr_6 are not removed and will point at patients that no longer exist.

### A real defect this found, in my own first version

`log_event` does `add` + `flush` and leaves the commit to the caller — as all
32 call sites in this service do. I committed the patient change first and
logged after, so the audit row was flushed into a transaction nobody committed
and discarded when the request ended. **The archive landed in production and
the audit entry did not**, while the SQLite suite stayed green: the fixture's
session keeps a flushed row visible to the next query, so the assertion passed
against a row that would never exist.

Fixed to one commit covering both (which also makes the change and its audit
record atomic). The test now calls `_db.session.rollback()` before counting, so
only a genuinely committed row survives — verified by reintroducing the bug.

### Verified

- 678 tests pass (18 new). Each new test verified load-bearing: reverting the
  default sort, the archive filter, the batch filter or the commit order turns
  the relevant ones red.
- Migration applied to prod: `archived_at timestamptz NULL` +
  `ix_patient_index_archived`; re-run is a clean no-op. 216 patients, 0 archived.
- Deployed (`docker-compose up -d --build`; host == in-image hash; no
  dependency drift, 32 packages; `/api/v1/health` 200).
- Live render against the real 216-row table: default 100 rows, 5 sort headers,
  Archive on every row, 3 batch Inspect links, archived view empty, malformed
  batch returns 0 rows, bogus sort key falls back to 200.
- Live archive → unarchive round-trip on Postgres: `archived_at` set then
  cleared, `is_active` untouched, hidden from default view, present in archived
  view, still findable by search, both audit rows committed. State restored.
