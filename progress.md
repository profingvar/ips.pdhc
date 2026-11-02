# IPS Server — Progress Tracking

Progress after each deployment plan step. Uses same numbering as `readme.md`.

---

## 1) Project scaffolding and configuration

### 1.a Create folder structure
- **Status:** complete
- Created `gateway/` with `app/`, `static/`, `migrations/`, `tests/`, `results/` directories

### 1.b Create `.env.example` and `config.py`
- **Status:** complete
- `.env.example` with all 14 variables documented
- `config.py` with Development, Production, Testing configs

### 1.c Create `requirements.txt`
- **Status:** complete
- SQLAlchemy upgraded to 2.0.48 for Python 3.14 compatibility
- Flask-SQLAlchemy 3.1.1 added (was initially missing)

### 1.d Create `Dockerfile` and `docker-compose.yml`
- **Status:** complete
- Dockerfile: Python 3.12-slim, gunicorn, port 9040
- docker-compose: db (PG 16 on 9041) + app (Flask on 9040) with healthcheck

### 1.e Create `start.sh`
- **Status:** complete
- Kills ports 9040–9043, checks Docker, starts DB, creates/activates venv, installs deps, runs app
- Ctrl+C graceful shutdown

### 1.f Copy `pdhc.css`
- **Status:** complete
- Copied to `gateway/static/css/pdhc.css`

### 1.g Create `CLAUDE.md`
- **Status:** complete

---

## 2) Database models (SQLAlchemy + Alembic)

### 2.a Define SQLAlchemy models
- **Status:** complete
- All 13 models implemented with portable GUID/JSONB types (work on both PostgreSQL and SQLite)
- Models: User, Clinic, UserClinicAssignment, ApiKey, FhirResource, PatientIndex, PatientClinicAssignment, IpsCard, IpsSnapshot, PushDestination, PushJob, AuditLog, CapabilityStatement

### 2.b Initialise Alembic
- **Status:** complete
- `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako` created
- Initial migration pending (first run uses `db.create_all()`)

### 2.c Bootstrap superuser logic
- **Status:** complete
- `bootstrap_service.py` creates SU on first startup when credentials configured and no users exist

### 2.d Tests for models and bootstrap
- **Status:** complete

---

## 3) Authentication and authorisation

### 3.a SSO token validation middleware
- **Status:** complete
- `auth_service.py` — resolves Bearer token via `OAUTH_BASE_URL/api/auth/me`

### 3.b API key validation
- **Status:** complete
- SHA-256 hashed lookup, checks is_active, expires_at, revoked_at, updates last_used_at

### 3.c AUTH_DISABLED bypass
- **Status:** complete
- Attaches synthetic dev user when AUTH_DISABLED=true

### 3.d Whitelist health/metrics
- **Status:** complete
- PUBLIC_ENDPOINTS set in auth_service.py

### 3.e Tests for auth flows
- **Status:** complete (covered via API key tests and endpoint tests with AUTH_DISABLED)

---

## 4) FHIR REST surface

### 4.a CapabilityStatement endpoint
- **Status:** complete — `GET /fhir/metadata`

### 4.b Patient CRUD
- **Status:** complete — POST, GET, PUT, search

### 4.c Clinical resource CRUD
- **Status:** complete — Condition, Observation, MedicationStatement, AllergyIntolerance, Immunization, Procedure, DocumentReference, DiagnosticReport

### 4.d $ips operation
- **Status:** complete — `GET /fhir/Patient/<id>/$ips` with full/minimal modes

### 4.e FHIR error handling
- **Status:** complete — OperationOutcome responses

### 4.f Tests for FHIR endpoints
- **Status:** complete

---

## 5) Application API

### 5.a Health and metrics
- **Status:** complete

### 5.b IPS card management
- **Status:** complete — CRUD + archive

### 5.c IPS snapshot management
- **Status:** complete — create, list, get metadata, get bundle (audited)

### 5.d Push destination management
- **Status:** complete — CRUD + deactivate

### 5.e Push job management
- **Status:** complete — create, list, get

### 5.f API key management
- **Status:** complete — create (returns plaintext once), list, revoke, rotate

### 5.g Audit log endpoint
- **Status:** complete — query with filters

### 5.h Clinic management
- **Status:** complete — CRUD

### 5.i Tests for application API
- **Status:** complete

---

## 6) IPS generation service

### 6.a IPS Bundle builder
- **Status:** complete — `ips_generator.py`

### 6.b Full vs minimal mode
- **Status:** complete

### 6.c FHIR R5 profile compliance
- **Status:** complete — IPS profile URL, LOINC section codes, emptyReason for absent sections

### 6.d Tests for IPS generation
- **Status:** complete

---

## 7) Audit service

### 7.a Audit event creation
- **Status:** complete — `audit_service.py`

### 7.b Audit sensitive reads
- **Status:** complete — ips_bundle_read audited

### 7.c Tests for audit logging
- **Status:** complete

---

## 8) Admin UI

### 8.a base.html
- **Status:** complete — PDHC design system, Lucide icons

### 8.b Dashboard page
- **Status:** complete — service status, resource counts, recent audit events

### 8.c Patient browser
- **Status:** complete
- `patients.html` — search by name/identifier, list with card & resource counts
- `patient_detail.html` — demographics, FHIR resources, IPS cards, snapshots
- Routes: `/admin/patients`, `/admin/patients/<guid>`

### 8.d Push monitor
- **Status:** complete
- `push_monitor.html` — destinations with job counts, jobs with status/attempts/errors, status filter, queue stats
- Route: `/admin/push`

### 8.e Tests for admin UI routes
- **Status:** complete — 28 tests in `test_admin.py`

### 8.f Documentation pages
- **Status:** complete
- `/admin/docs` — index page with links to all docs + download table
- `/admin/docs/api` — full API endpoint reference (FHIR + application API, all methods, params, examples)
- `/admin/docs/capability` — FHIR R5 CapabilityStatement viewer (overview, resource table, interaction matrix, search params, operations, raw JSON)
- `/admin/docs/manual` — operator manual (admin UI guide, IPS workflow, API key management, audit, maintenance)
- `/admin/docs/technical` — technical documentation (architecture, stack, data model, FHIR compliance, security, deployment)
- All docs downloadable as standalone HTML (`/admin/docs/*/download`)
- Uses self-contained `docs_base.html` template (inline CSS, no external deps) for offline viewing
- 11 doc tests in `test_admin.py`

---

## 9) Docker and deployment

### 9.a–9.d Docker stack
- **Status:** complete
- `docker-compose.yml` with db + app services
- Dockerfile with Python 3.12-slim + gunicorn
- `start.sh` lifecycle script
- `.env.example` fully documented

### 9.e Test full Docker Compose stack locally
- **Status:** complete
- PostgreSQL on port 9041 — healthy
- Flask on port 9040 — connected to PG, all endpoints working
- Live smoke test: health, FHIR metadata, patient create, $ips generation, metrics — all passed

---

## 10) API endpoint test script (Rules 9, 20)

### 10.a `test_api_endpoints.py`
- **Status:** complete — 92 tests covering all endpoints against capability statement

### 10.b `test_fhir_compliance.py`
- **Status:** covered within test_api_endpoints.py (IPS profile validation, FHIR R5 structure, OperationOutcome, section codes)

### 10.c Full test suite run
- **Status:** complete — results saved

---

## 12) Server deployment

### 12.a Package for deployment
- **Status:** complete
- Nginx config: `gateway/server_configs/ips.pdhc.se.conf`
- Deployment instructions: `gateway/server_configs/deploy.md`
- Covers: packaging, unpack, .env setup, Docker start, nginx proxy, SSL, SSO integration notes

### 12.b–12.e Server setup, nginx, port allocation, bootstrap
- **Status:** ready for operator — all configs and instructions prepared
- Port allocation documented: 9040 (API), 9041 (PostgreSQL), 9042 (Admin UI)
- DNS already configured: `ips.pdhc.se` → `178.174.164.196`

---

## Test Results — 2026-03-23

**169 tests passed, 0 failed**

Results saved to: `./results/2026-03-23T07-56-57Z_docs_results/`

| Test file | Tests | Result |
|-----------|-------|--------|
| `test_admin.py` | 28 | all passed |
| `test_api_endpoints.py` | 92 | all passed |
| `test_app_api.py` | 21 | all passed |
| `test_fhir_endpoints.py` | 12 | all passed |
| `test_health.py` | 3 | all passed |
| `test_models.py` | 13 | all passed |
| **Total** | **169** | **all passed** |

### Tests deployed (test_admin.py — admin UI + docs):
- **Dashboard** (4): returns HTML, includes CSS, shows counts, shows audit events
- **Patient Browser** (8): empty page, lists patients, search match, search no match, detail view, detail 404, shows resources, shows cards & snapshots
- **Push Monitor** (5): empty page, shows destinations, shows jobs, filter by status, stats display
- **Docs Index** (2): page renders, has download links
- **API Reference** (2): page with all endpoint sections, download as HTML
- **Capability Statement** (3): page with FHIR version and resources, shows $ips operation, download
- **Operator Manual** (2): page with workflow and key management sections, download
- **Technical Docs** (2): page with architecture/security/data model, download

### Tests deployed (test_api_endpoints.py — comprehensive):
- **Public endpoints** (2): health, metrics
- **FHIR CapabilityStatement** (4): returns CS, declares 9 resource types, Patient has $ips op, Patient search params
- **FHIR Patient CRUD** (9): create, reject wrong type, read, read 404, update, update 404, search by family, search by identifier, empty search
- **FHIR Clinical CRUD** (26): create/read/search for all 8 types (Condition, Observation, MedicationStatement, AllergyIntolerance, Immunization, Procedure, DocumentReference, DiagnosticReport) + unsupported/wrong type rejection
- **FHIR $ips** (6): full mode (profile, Composition, Patient), minimal mode (sections), sections with emptyReason, 404, timestamp
- **IPS Cards** (10): create, missing guid, nonexistent patient, list, filter by patient, get, get 404, update mode, update title, archive
- **IPS Snapshots** (5): create, list, get metadata (no bundle), get bundle, get 404
- **Push Destinations** (6): create, missing fields, list, get, update, deactivate
- **Push Jobs** (6): create, missing fields, nonexistent snapshot, list, filter by status, get
- **API Keys** (6): create (plaintext once), list (hides secret), revoke, revoke 404, rotate, rotate 404
- **Audit Log** (4): query all, filter by event_type, limit, audit records bundle read
- **Clinics** (7): create, missing name, list, get, get 404, update, deactivate
- **Admin UI** (1): dashboard returns HTML with CSS

### Live PostgreSQL smoke test (2026-03-20):
- `GET /api/v1/health` — `{"status":"ok","database":"connected"}`
- `GET /fhir/metadata` — FHIR 5.0.0, 9 resource types
- `POST /fhir/Patient` — Created Patient with UUID
- `GET /fhir/Patient/<id>/$ips` — IPS Bundle: 2 entries, type=document
- `GET /api/v1/metrics` — counts: 2 patients, 2 resources, 3 audit events

---

## Status: Feature complete

All deployment plan steps (1–12) are complete. The application is ready for server deployment by the operator following `gateway/server_configs/deploy.md`.

---

## 2026-06-02 — `GET /api/v1/clinics/{guid}/patients` (cross-service)

Added one endpoint to expose the patient list for a clinic, joining
`PatientClinicAssignment → PatientIndex`. Used by `sim.pdhc` Cohort
Builder (Step A of the plandef-driven flow): "pick an organisation,
get its patients, simulate against them".

- Route in `gateway/app/api/clinic_routes.py`, `@require_auth` like the
  rest of the blueprint.
- `is_active = true` filter on `PatientIndex`; clinic-level `is_active`
  deliberately not filtered so audit/reporting still works against
  retired clinics.
- Order by `(family_name, given_name)`.
- 404 with `{"error": "Clinic not found"}` for unknown clinic.
- Empty clinic → `[]` with 200.
- Patient assigned to two clinics appears in both lists (M2M via
  `PatientClinicAssignment` with `UniqueConstraint(patient_guid,
  clinic_guid)` so no dedupe needed).
- 5 new tests in `TestClinicPatients`; **174/174** suite green.

Docs updated per Rule 25: API reference (`docs_api.html`), operator
manual (`docs_manual.html` — new "Clinic patient lists (cross-service)"
section), technical reference (`docs_technical.html` — new "Patient ↔
clinic (organisation) relationship" sub-section under Data Model + API
surface row bumped 4 → 5 endpoints).

Pre-existing drift on `gateway/` (≈1100 lines across 15 unrelated
files including `admin.py +597`) **not committed in this pass** — it
predates this session and is the same uncommitted-but-deployed pattern
seen on contract.pdhc / plan.pdhc; needs a separate audit.

---

## Access-model reform D1 (#404) — 2026-07-04 (commit fccb302)

Added patient opt-out flags to `PatientIndex` for the SSO reform (rollup
#396): `ehds_opt_out`, `quality_registry_opt_out` (Bool, default False)
and `consented_research_projects` (JSONB list of ResearchProject GUIDs).
Added `to_dict()` fields + `primary_care_unit_guids()` helper.

Reconciliation — the other two v3-spec consents already exist richer and
were NOT duplicated: `allow_sharing_in_care` → existing `PatientConsent`
(#198, per-caregiver cohesive-care consent); primary care units →
existing `PatientClinicAssignment` rows.

ips uses `db.create_all()` (never alters existing tables) → prod needs
the idempotent ALTER `gateway/migrations/add_reform_patient_flags.sql`
(operator runs it post-deploy). Tests: +3 in `test_models.py` (17/17).
Ticket #404 closed. D2 (#405, personnummer confinement) verified ips is
the correct pnr home; guard test lives in sso. Wave-3 staff-route
adoption tracked in #420.

## Spärr operator runbook — clinical-lead sign-off (#241, 2026-08-20)
`docs/sparr_operator_runbook.md` §8 review log signed off (follow-up to
#209): reviewed version `834507f`, approved per session authorisation.
Clears the admin-lift HTML form for production. Pairs with the #242
patient-copy legal sign-off — both gated the spärr patient-portal
go-live and are now cleared.

## 2026-10-07 — /analysis-filter answered 500 on a malformed guid

Found while fixing cdr #730. `PatientIndex.guid` is a UUID column, so
`.filter(PatientIndex.guid.in_(guids))` raised at the driver — "badly formed
hexadecimal UUID string" — whenever any guid was not a well-formed UUID, and the
endpoint answered **500**.

That is the worst available answer for a consent gate. The caller gets an
exception rather than a verdict, and a 500 is indistinguishable from ips being
down: cdr's `_analysis_filter` converts it to `IpsUnreachable` and fail-closes
the **whole read**, reporting a sibling outage. So one malformed guid anywhere
in a cohort denied the entire cohort and blamed the wrong service.

Malformed guids are now treated as **unknown** rather than fatal: they get empty
flags, so they fail closed for that patient alone, and they are named in
`excluded` with `reason: malformed_guid` so the caller can see it sent something
unusable. Per-patient fail-closed beats per-request, and neither should be a
500. A warning is logged with the first five offenders.

Deliberately not a 400: refusing the request would also deny the whole cohort
for one bad entry, which is the behaviour being removed.

**The unit suite cannot reproduce the 500** — the test DB is SQLite, which does
not coerce UUIDs, so the old code does not raise there. The three new tests pin
the new contract (excluded-by-name, never silently dropped, all-malformed still
200); two of them fail against the old code. Only Postgres reproduces the
original bug, so cdr's production sibling smoke is the real verification, and it
is what found it.

    401 passed, 1 failed — the failure is PRE-EXISTING and unrelated
    (test_patient_portal_html: a Swedish legal-review banner), verified by
    stashing the change and re-running.

Deployed to `/usr/local/www/pdhcips/gateway` (note: not `/usr/local/www/ips.pdhc`
— that path does not exist; the compose working_dir is the source of truth).
`patient_routes.py` was diffed against the local pre-change baseline first and
was identical. Backup at `~/backups/predeploy/ips.pdhc/20261007T092918Z/`.

Verified from all three CDRs in-container:
`VERDICT OK allowed=0 excluded=1 reasons=['malformed_guid']`.

## 2026-10-07 — euIPS Phase A: #789 personnummer, #790 move the generator

First work on epic #788. 455 tests pass (443 before + 12), with one
pre-existing unrelated failure confirmed by stashing
(`test_patient_portal_html::test_blocks_list_shows_legal_review_banner_when_draft`,
fails identically on the untouched tree). Not deployed yet.

### #789 — the production baseline is worse than the ticket said

Ran the new validator's logic against the live database:

```
PRODUCTION BASELINE — 150 patients
  valid Swedish personnummer : 0
  foreign identifier system  : 10  (http://hl7.org/fhir/sid/us-ssn)
  BROKEN Swedish personnummer:
       140  malformed (wrong length or shape)
```

**Zero of 140 are valid**, not the ~90% the ticket estimated. The earlier 10%
figure came from testing the Luhn digit *after* manually stripping the doubled
century; in the data as it actually stands every value fails on shape before
the check digit is reached. Worth correcting in the ticket rather than leaving
a number that understates it.

One line caused both halves (`admin.py:743`):

```python
personnummer = f"19{mp['birth'].replace('-', '')}-{random.randint(1000, 9999)}"
```

`mp['birth']` is already `YYYY-MM-DD`, so the `"19"` doubled the century, and
the last digit is a Luhn checksum rather than a free number.

`app/services/personnummer.py` is now the one definition — `build`,
`normalise`, `is_valid`, `describe_invalid`, and the OID — used by all three
paths that mint or accept one: the generator, the admin create form and
`POST /api/v1/clinics/<guid>/patients`. Three copies of this would drift, which
is what #784 and #786 both had to undo.

**The decision on existing rows: fix forward.** Restamping would have to
rewrite `PatientIndex.identifier_value` AND the identifier inside each Patient
`resource_json` — a migration, not an update — and the rows are synthetic. Same
choice #781 took for `patient_org_guid`. `flask check-personnummer` is the
other half of that decision: leaving legacy rows is only defensible if the
number is visible rather than assumed.

**The 10 US SSNs are reported separately as a foreign identifier system, not as
broken.** They are from the Synthea import. Counting them with the malformed
rows would overstate the defect and imply a fix that would be wrong.

**Validation warns, it does not reject**, on both accepting paths. An operator
may be recording a real patient with imperfect details, and refusing the save
would discard the rest of the record; `POST /clinics/<guid>/patients` is a live
endpoint where turning a 201 into a 400 is a breaking change belonging in its
own ticket. Validation is also scoped to the Swedish OID — a caller passing its
own `identifier_system` is not asserting Swedish format and must not be judged
against it.

### #790 — moving it needed more than moving the markup

The block's organisation select is labelled "synced from SSO", and that sync
ran in the DASHBOARD view (`orgs = _sync_sso_organisations()`). The patients
view passed only `clinics`, a plain DB read. Moving the markup alone would have
rendered "No organisations — check SSO connection", and a newly created SSO
organisation would not have appeared until somebody visited the dashboard.

`_sync_sso_organisations()` ends with exactly the query `clinics` ran, so the
two are the same list and the sync only refreshes it first — and it already
degrades gracefully when SSO is unreachable. The patients view now calls it.

### Three mistakes of mine, all caught before they shipped

1. **A `NameError` hidden in error handling.** My new warning in
   `clinic_routes.py` logged `clinic_guid`; the route parameter is `guid`. It
   would have raised only on the warning path — that is, only when someone
   submitted a bad personnummer. A crash reachable only once something is
   already wrong. Found by scanning for unresolved names, not by a test.
2. **A mangled import.** Inserting the new import after the anchor
   `"from app.models.patient_index import PatientIndex"` matched the PREFIX of
   `...import PatientIndex, PatientClinicAssignment`, splitting the line and
   leaving `PatientClinicAssignment` attached to my import. Every test errored
   at collection, so it was loud.
3. **A test that passed for the wrong reason.** `"Akademiska" in body` on
   `/admin/patients` passed against the untouched tree, because the Create
   Patient form on that page already lists clinics. It matched the wrong form.
   Now scoped to a slice of the generator's own `<form>`, and it fails on the
   untouched tree as it should.

With the fix stashed, 9 of the 12 endpoint tests fail. The 3 that pass either
way are regression guards: the POST target and field names are unchanged, junk
input does not 500, and the identifier in `resource_json` matches the index
column (which was true before too — the old generator wrote the same wrong
value to both places).

### 2026-10-07 — Phase A DEPLOYED

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backup `miserver:~/backups/predeploy/ips.pdhc/20261007T191158Z/`.

Live root is **`/usr/local/www/pdhcips/gateway`**, resolved from the container's
compose label. `/usr/local/www/ips.pdhc` does not exist, and a hardcoded guess
was wrong here once before (#730). There is also a stale nested copy at
`/usr/local/www/pdhcips/pdhcips/gateway/` which is NOT what runs; the deploy
touched only the path the container reports.

Verified in production:

| check | result |
|---|---|
| `app/services/personnummer.py` in the image | present |
| the live personnummer assignment | `personnummer = pnr.build(mp["birth"])` |
| `generate_mock_data` in `dashboard.html` | **0** |
| `generate_mock_data` in `patients.html` | **1** |
| `flask check-personnummer` against the live DB | runs; 150 patients, 0 valid, 10 foreign, 140 malformed |

### Three of my verification steps were wrong, and two looked like failures

None of these were deploy problems. All three were flaws in how I checked.

1. **A check that matched its own explanation.** `grep -c "19{mp"` reported
   "old doubled-century line still present: 1". It was matching the NEW code's
   comment, which quotes the line it replaced. This is #729's trap exactly, and
   I have cited it twice today and still walked into it. Fixed by grepping the
   assignment with comment lines excluded — which shows the single live
   assignment is `pnr.build`.
2. **Grepping a literal path that the template never contains.** The form uses
   `url_for('admin.generate_mock_data')`, so `grep "mock-data"` returned **0 on
   both pages** and looked as though the move had failed entirely. Grepping the
   endpoint name gives the real answer: 0 on the dashboard, 1 on patients.
3. **Asking for an in-container pytest run that cannot work.** `tests/` is
   listed in `.dockerignore`, so it is deliberately absent from the image and
   the run reported "no tests ran" — which reads like a failure. The suite runs
   on the development checkout. The test files are still copied to the host so
   the server source matches git; they simply do not enter the image.

The script in `scripts/deploy_789.sh` carries the corrected checks, with each
of the three mistakes written down beside the check that replaced it.

### Still true after the deploy

The 140 malformed and 10 foreign identifiers are unchanged — that is the
fix-forward decision, not an oversight. Newly generated patients are valid;
`flask check-personnummer` is how that number is watched rather than assumed.

## 2026-10-07 — #791 DECISION TAKEN and implemented (unblocks Phase C)

Operator: "go with your recommendation for 791". 463 tests pass (443 + 20),
same single pre-existing unrelated failure. Full decision record in
`plans/euips_reform.md`; the short version:

* **Section content stays in `fhir_resources`.** No new tables for clinical
  content — it is already generic, every euIPS section is a FHIR resource, and
  nine services read this service.
* **An explicitly-absent section is a real resource carrying the IPS
  absent/unknown code.** That makes PRESENT / EXPLICITLY_ABSENT / MISSING
  distinguishable, which is the thing the reform needed: 110 of 150 patients
  had no rows anywhere, and "no row" could not be told from "nothing to
  report".
* **Status is computed, not stored.** `GET
  /api/v1/patients/<guid>/euips-sections`. A stored copy of a derivable fact is
  the #779 / #771 shape.
* **One schema addition:** `patient_index.generation_batch_guid`, nullable, no
  default, no index.
* **Codes flagged unverified** in the module AND in the endpoint's response.
  EU-addition sections carry `None` rather than a guessed code, with a test.

### Two of my own errors, caught before shipping

1. **The migration said `VARCHAR(36)` where the column must be `UUID`.**
   `models/base.py::GUID` resolves to `PG_UUID(as_uuid=True)` on postgresql,
   and `patient_index.guid` is a real `uuid` column — confirmed against
   `information_schema` rather than assumed. psycopg2 would have adapted bound
   UUID objects to strings, so a varchar column would have *appeared* to work
   while disagreeing with the model. That is exactly the UUID-versus-string
   mismatch that hid #730's 500, and it would have surfaced later and
   elsewhere.
2. **`_is_uuid` was a nested function inside `analysis_filter`** (added there
   by #730), and the new route called it at module scope — a `NameError` on
   every request. Hoisted to module scope so there is one definition rather
   than a second copy, which is what #784 and #786 each had to undo.

### Not yet applied to production

`gateway/migrations/add_generation_batch_guid.sql` has not been run. It is
additive, nullable and idempotent, but it is still an ALTER on a table that
nine services read, so it wants an explicit go rather than riding along with a
code deploy.

### 2026-10-07 — #791 migration applied and code DEPLOYED

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backups: `20261007T192237Z/patient_index_before.sql` (pg_dump before the ALTER)
and `20261007T192346Z/` (the code).

**Order mattered, and the script enforces it.** The new model selects
`generation_batch_guid`, so shipping the code before the column exists would
make EVERY `PatientIndex` query fail — a total outage of the service nine
siblings depend on. The migration ran first, and `deploy_791.sh` carries an
ordering gate that queries `information_schema` and aborts with exit 7 if the
column is absent, rather than trusting that the migration was remembered.

Applied: `ALTER TABLE patient_index ADD COLUMN IF NOT EXISTS
generation_batch_guid UUID;` → `uuid`, nullable, no default. 150 patients, 0
with a batch, which is correct: an existing row is not from a tracked batch.

**The Phase C baseline, now measured by the shipped code in production:**

```
patients: 150
euIPS-conformant (all 3 required present or explicitly absent): 40
no content in ANY section: 110
```

This independently reproduces the figure derived from raw SQL earlier in the
day, now computed by `euips_sections.status_for_resources` itself. That is the
number #793 has to move.

**Compatibility verified, not assumed.** Inside the container, against live
data: the exact `/clinics` join request.pdhc uses for the #779 gate still
returns, `Clinic.guid` and `Clinic.organisation_guid` are still distinct
fields, a `PatientIndex` row loads with `generation_batch_guid=None`, and every
`to_dict` key consumers read is still present with the new one added
additively. Externally: health 200, `/clinics` 401, `analysis-filter` 405 on
GET (it is POST-only; a POST gives 401), the new endpoint 401. Zero error lines
in the logs.

In-container checks confirm `CODES_VERIFIED: False` and 17 sections split
3/4/7/3 — so the catalogue that shipped is the one the document describes, and
the unverified-codes flag is live rather than a local-only intention.

**Rollback asymmetry, stated because it is easy to get wrong:** the code
rollback does NOT undo the migration, and should not. The column is nullable
with no default, so the previous code simply ignores it. `DROP COLUMN` only if
genuinely required.

## 2026-10-07 — #793: the three REQUIRED sections may never be empty

476 tests pass (463 + 13), same single pre-existing unrelated failure. 6 of the
13 new tests fail against the untouched tree; the 7 that pass either way are
regression guards, because the generator's FULL path was already conformant.

### That sharpens what was actually wrong

The 110 non-conformant production patients came from the **`skip_clinical`**
path, which created a Patient and a clinic assignment and nothing else. The
full path already emitted allergies, conditions and medications. So #793's real
effect on live data is the skip_clinical case — worth stating precisely rather
than implying the whole generator was broken.

### The decision the ticket asked for

`skip_clinical` now emits the three required sections as **explicit absent
assertions** instead of skipping them. It exists so sim.pdhc can own the
clinical data without two sources of truth, which is a good reason — and not a
reason to create an invalid summary in the meantime. sim's real content
supersedes them later, because `status_for_resources` prefers real content over
a stale absent assertion. It still genuinely skips the optional content, with a
test pinning that, or its purpose would be lost.

### A defect in what #791 shipped, found by starting #793

`is_absent_assertion` checked `code` and `medicationCodeableConcept`. This
codebase writes **`medication`** — all 119 pre-existing MedicationStatement
rows use it, confirmed by querying `jsonb_object_keys` in production. So a
medications absent assertion was **undetectable**, silently turning
EXPLICITLY_ABSENT back into MISSING for one of the three REQUIRED sections.
#793 would have appeared to work while the status endpoint reported a hole.

Now driven by `_CODE_BEARING_FIELDS`, covering `code`, `medication`,
`medicationCodeableConcept`, `vaccineCode` and `type`, and handling both
CodeableConcept and R5 CodeableReference (`{"concept": {...}}`). A plain string
field (R4 `AllergyIntolerance.type`) is inert rather than an exception.

### Two vocabularies that disagreed

Moving generation into `euips_required.py` left `_CONDITIONS`, `_MEDICATIONS`
and `_ALLERGIES` dead in `admin.py`. Deleting them turned up something worth
recording: **the two copies disagreed.** `admin.py` labelled SNOMED
`91936005` as "Peanuts"; the surviving list labels it "Allergy to penicillin".
One is wrong, and nothing would have caught it.

That is the concrete case for `CODES_VERIFIED = False`. The discrepancy is
written at the deletion site as a specific item to settle when the terminology
is verified against the IPS IG — the codes belong to plan.pdhc and
termbank.pdhc, not here.

### Narrative, not only codes

Every resource carries `text.status` and an XHTML `text.div`, because euIPS is
explicitly hybrid and the guideline calls the narrative the safety net — "what
a clinician abroad sees". A coded-only entry passes a FHIR validator and fails
the purpose of the section. Display strings are escaped, since they land inside
XHTML.

### The flash message no longer asserts what it does not check

It used to list the section types it had supposedly created. It now counts how
many of the batch carry all three required sections and says so, and shows a
warning rather than a success when that is not all of them.

### 2026-10-07 — #793 DEPLOYED

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backup `miserver:~/backups/predeploy/ips.pdhc/20261007T193331Z/`.
No migration — #793 adds no column, and the deploy script's ordering gate was
removed rather than left in place asserting something untrue.

**Verified in production WITHOUT writing any data.**
`required_sections_for` is a pure function, so the live code could be exercised
directly instead of generating patients into the production registry:

| check | result |
|---|---|
| live code, normal mode | **200/200 conformant** |
| live code, `skip_clinical` mode | **50/50 conformant** |
| medications absent assertion detected | True — the #791 defect this ticket found |
| every resource carries XHTML narrative | True |
| dead `_CONDITIONS` / `_MEDICATIONS` / `_ALLERGIES` in admin.py | 0 remaining |
| existing patients | 150, **40 conformant** — unchanged, by design |

Consumers after the deploy: health 200, `/clinics` 401, `analysis-filter` 401
on POST. Zero error lines.

**The existing 150 are deliberately untouched.** 40/150 before, 40/150 after.
That is the #789 fix-forward decision applied consistently: new patients are
conformant, old synthetic rows are not restamped, and the number stays visible
rather than assumed. Generating a batch is what will move it, which is #797.

**Worth keeping from this deploy:** exercising a pure function inside the
container is a far better production check than creating test data and deleting
it. It proves the shipped code behaves, leaves no residue in a patient
registry, and needs no cleanup that could itself go wrong.

## 2026-10-07 — #794: the four RECOMMENDED sections

490 tests pass (476 + 14), same single pre-existing unrelated failure. 6 of the
14 new tests fail against the untouched tree — the three measured defects below,
plus narrative.

### Three defects, each measured in production first

1. **Medical devices did not exist.** No `Device` or `DeviceUseStatement` had
   ever been written: the live resource types were Observation, Patient,
   MedicationStatement, Condition, Immunization, AllergyIntolerance,
   DiagnosticReport, Procedure. One of the four recommended sections was simply
   absent from the simulator. Now `Device` + a `DeviceUseStatement` that
   references it, including a **continuous glucose monitoring sensor** —
   deliberately, because cgm.pdhc is a live provider here and the simulator
   should describe the same object as the real integration.
2. **Diagnostic reports linked to nothing.** Queried
   `jsonb_object_keys`: all 61 live rows carry `code`, `status`, `conclusion`,
   `effectiveDateTime`, `subject` and **no `result`**. A diagnostic-results
   section whose reports reference no observations is a header with a sentence
   attached, and the results are the part a clinician reads. Lab panels now
   emit their Observations first and the report references them, LOINC-coded
   with UCUM units. Imaging reports keep a conclusion and no numeric result,
   which is correct for imaging — the two are built from separate lists rather
   than forced into one shape.
3. **Immunisation dates were generation time.** 97 live rows across 40 distinct
   dates, each the moment its batch ran, so an 80-year-old's childhood vaccine
   was dated today. Dates now derive from the patient's birth date against a
   rough Swedish schedule, clamped so nothing lands before birth or in the
   future, and a vaccine the patient is too young for is skipped rather than
   back-dated.

### The distinction from #793, made explicit

A required section may never be empty. A **recommended** one may. So each
produces one of three outcomes — content, an explicit "none known", or nothing
at all — and all three are valid. Verified across 200 generated patients that
immunisations, procedures and devices each produce all three;
`diagnostic_results` produces two, because IPS defines no absent code for it
and inventing one is forbidden by the plan.

This matters downstream: **#799 must not report a MISSING recommended section
as a failure.**

### A FHIR cardinality error caught by probing, not by a validator

The immunisation absent-assertion initially had no `occurrenceDateTime`, and
FHIR makes `Immunization.occurrence[x]` required (1..1) — so the resource was
structurally invalid. There is no FHIR validator in this test path, so nothing
would have said so; a probe over 400 generated patients found it. Fixed by
setting a real date, with a note that IPS may instead use a
`data-absent-reason` extension on `_occurrenceDateTime` and that satisfying the
cardinality is the choice that cannot be silently wrong while
`CODES_VERIFIED` is False.

### Dead vocabularies removed, and what the comparison showed

`_IMMUNIZATIONS`, `_PROCEDURES` and `_DIAGNOSTIC_REPORTS` had no remaining
reader. Unlike the #793 removal these did **not** contradict the surviving
lists — every shared code carried a compatible display, and the one apparent
clash (`J07BM01` as "HPV vaccine" versus "Human papillomavirus") was my own
string comparison failing, not a disagreement.

One redundancy was dropped: the old list carried BOTH LOINC `58410-2`
"Complete blood count" and `11502-2` "Full blood count" — two codes for one
concept, which would have made a cohort look as though it contained two
different tests.

`_OBSERVATIONS` stays: vital signs are an OPTIONAL section and #795 owns them.

### 2026-10-07 — #794 DEPLOYED

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backup `miserver:~/backups/predeploy/ips.pdhc/20261007T194253Z/`.
Verified by exercising the pure generator inside the container — no patients
created in the production registry, nothing to clean up.

Live code over 300 generated patients:

```
immunisations        PRESENT 224  EXPLICITLY_ABSENT 41   MISSING 35
procedures           PRESENT 121  EXPLICITLY_ABSENT 99   MISSING 80
devices              PRESENT  60  EXPLICITLY_ABSENT 121  MISSING 119
diagnostic_results   PRESENT 198                         MISSING 102
lab reports carrying results        : 198
dangling references                 : 0
reports saying nothing              : 0
dates before birth or in the future : 0
```

All three outcomes occur for the three sections that have an IPS absent code;
`diagnostic_results` has two, because IPS defines none for it.

**A number in the deploy output that looks wrong and is not.** It reported
"Device / DeviceUseStatement written : 181 / 60", and the builder emits those
1:1, so 181 vs 60 reads like a defect. It is not: a device **absent
assertion** also has `resourceType: Device`. Re-measured separately — 60 real
Devices, 121 absent assertions, 60 use statements, and 60 + 121 = 181 exactly.
Real devices pair 1:1 with a use statement as intended.

The lesson is about the probe, not the code: counting by `resourceType` lumps
content together with absent assertions, which is precisely the distinction
#791 exists to make. A count that ignores `is_absent_assertion` will mislead
every time.

Consumers after the deploy: health 200, `/clinics` 401, `analysis-filter` 401
on POST, zero error lines. `_OBSERVATIONS` confirmed still present for #795.

## 2026-10-07 — #795: the seven OPTIONAL sections, and a conformance bug in #791

508 tests pass (490 + 18), same single pre-existing unrelated failure. 9 of the
18 new tests fail against the untouched tree.

### Starting #795 exposed a CONFORMANCE-AFFECTING bug in what #791 shipped

`Condition` is shared by 3 sections and `Observation` by **7**, and
`status_for_resources` did not discriminate. Measured:

* one vital-sign Observation made **seven** sections read PRESENT — including
  pregnancy, travel history and patient-provided information;
* one active Condition made `past_illnesses` and `pregnancy` read PRESENT;
* and the serious one: a patient with only a **resolved** Condition made
  `problems` read PRESENT, so an empty ACTIVE problem list was called
  **conformant**. `problems` is one of the three required sections, so this
  was not cosmetic.

Fixed with an explicit per-section `discriminator` and `section_matches`:
Condition by `clinicalStatus`, Observation by `category`, pregnancy by code
set, patient-provided by whether the performer is the subject. Absent
assertions are attributed by their own section-specific absent code, so a "no
known problems" Condition cannot also satisfy `past_illnesses`.

A structural test now asserts that **every section sharing a resource type has
a discriminator**, so a future section cannot silently claim its neighbours'
resources.

### The pregnancy trap, and the trap inside the trap

The ticket warned that a pregnancy on a male or an 80-year-old is nonsense.
True for a CURRENT pregnancy — but pregnancy **history** is perfectly ordinary
for an 80-year-old woman, and refusing it would be an error in the other
direction: a summary that denies she ever had children. So the two are gated
separately:

* current pregnancy status — female, age 15–50
* pregnancy history (gravida/para) — female, age 20+, no upper bound

Never for a male or unknown-sex patient, in either form.

### Advance directives verified isolated from care consent

Before writing it: `consents_routes.py` never touches `fhir_resources`, so a
FHIR `Consent` cannot reach `/consents/check` — which request.pdhc and
contract.pdhc both call for the cohesive-care gate (Lag 2022:913 §5). The
directive also carries the `adr` consent-scope code, and a test asserts
`patient_consents` stays empty when directives are generated.

### A #793 test that became wrong for a correct reason

`test_the_problem_list_contains_only_active_conditions` asserted that EVERY
Condition row was active. That was true while #793 was the only thing emitting
them; #795 adds resolved ones, so the assertion broke. It was testing the
absence of a feature rather than the separation. Narrowed to the real
invariant: whatever `problems` matches is active, whatever `past_illnesses`
matches is resolved, and no condition is in both.

### `_mock_patient_resources` is gone

Vital signs were the last thing in it. Every euIPS section now has a dedicated
module in obligation order — `euips_required` (#793), `euips_recommended`
(#794), `euips_optional` (#795). The old helper emitted Observations with **no
`category` at all**, so under the new discrimination its observations would
have been attributable to no section — another reason it could not stay.

### 2026-10-07 — #795 DEPLOYED

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backup `miserver:~/backups/predeploy/ips.pdhc/20261007T195723Z/`.

The #791 bug asserted against the LIVE code after deploy:

```
one vital-sign Observation marks PRESENT: ['vital_signs']      (was 7 sections)
one RESOLVED Condition: problems=MISSING past_illnesses=PRESENT conformant=False
                                        (was problems=PRESENT, conformant=True)
sections sharing a type with no discriminator: none
```

Live generator over 250 patients: vital_signs 226, past_illnesses 116,
pregnancy 20, social_history 153, functional_status 61, plan_of_care 63,
advance_directives 36 — each present for some patients and absent for others,
which is what optional means. And the four invariants that would be nonsense:

```
pregnancy on a male patient         : 0
pregnancy on a child                : 0
CURRENT pregnancy over the age bound: 0
Observations with no category        : 0
```

**The baseline is still 40/150, and that is the reassuring answer.** If the
stricter discrimination had REDUCED the count, some of those 40 would have been
counted conformant only because of the over-reporting bug. It did not, so all
40 genuinely carry an active problem list rather than only resolved
conditions. Worth checking rather than assuming the fix was conservative.

Consumers: health 200, `/clinics` 401, `analysis-filter` 401 on POST, zero
error lines.

## 2026-10-07 — #796: the three EU additions, and the MDR reason alerts are tagged

522 tests pass (508 + 14), same single pre-existing unrelated failure. 7 of the
14 new tests fail against the untouched tree.

### The finding that shaped medical alerts

Measured before writing anything: **no `Flag` resource exists anywhere on the
platform.** Zero rows in ips, and nothing in request.pdhc, cdr.pdhc or
gateway.pdhc emits one. So these are the platform's FIRST Flags and the
simulator is setting the convention.

That is an MDR question rather than a tidiness one. plan.pdhc authors
thresholds (out of scope); **request.pdhc applies them and alerts (in scope,
likely Rule 11)**. If that path later emits computed alerts as Flags and the
simulated ones carry no provenance, the ambiguity is created **retroactively**
and test data that looks clinical pollutes the evidence for a technical file.

So every Flag carries `meta.tag` = `urn:pdhc:provenance#simulated`, says
"SIMULATED ALERT" in its narrative, and names the simulator as author. The tag
is at resource level deliberately, so it survives being read out of a bundle,
a search result or an export.

`is_simulated()` is the read side, and a test pins that it does **not** default
to true for an untagged resource — defaulting the other way would make a
genuinely computed alert look like test data, which is the same error
reversed.

### Travel history: the code is settled PROVISIONALLY and labelled as such

#795 left `TRAVEL_CODES` empty rather than guess. #796 had to settle something,
so it uses SNOMED `420008001` ("Travel") — recorded as a provisional choice in
one place, covered by `CODES_VERIFIED = False`, not asserted as a verified
binding. Travel is stored as an `effectivePeriod` rather than an instant,
because "when did you travel" is a window and the window is what relates it to
an illness, which is the whole reason the section exists.

### Two more instances of the over-reporting class

Writing #796 turned up two more sections swallowing their neighbours, after the
three #795 found:

* **travel history carries the `social-history` category**, so a
  category-only rule made one travel observation mark both `social_history`
  and `travel_history` PRESENT;
* **patient-provided information carries the `survey` category**, which
  functional status also uses, so one patient-reported observation marked both.

Both fixed by making the GENERAL section subtractive — it yields to the more
specific one. `obs_social_history` excludes pregnancy and travel codes;
`obs_survey` excludes patient-asserted resources. The cut direction matters and
is tested: the same survey recorded by a clinician is functional status, while
asserted by the patient it is patient-provided.

**All six Observation-based sections now attribute to exactly one section**,
with a test over one resource of each kind. That is the invariant worth
holding; five separate overlaps were found by looking for it rather than
assuming the discriminators were sufficient.

### A #795 test superseded for a correct reason

`test_travel_history_stays_missing_until_796_defines_a_code` asserted
`TRAVEL_CODES == frozenset()`. That was the right guard while no code was
chosen; #796 chooses one. Narrowed to the invariant that survives — a
smoking-status observation is social history and not travel history, whatever
`TRAVEL_CODES` contains — with the "is it still unverified" question pinned in
#796's tests, where the decision lives. Same shape as the #793 problem-list
test earlier today.

### 2026-10-07 — #796 DEPLOYED

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backup `miserver:~/backups/predeploy/ips.pdhc/20261007T201034Z/`.

Asserted against the live code:

```
TRAVEL_CODES: ['420008001']   CODES_VERIFIED: False
each Observation kind -> its section:
  vital sign / social history / functional status / travel /
  patient-provided / pregnancy      -> exactly one section each
kinds matching more than one section: 0
Flags generated: 74, WITHOUT the simulated tag: 0
is_simulated on an untagged Flag: False
```

The last line is the one worth keeping: `is_simulated` must not default to
true. Defaulting the other way would make a genuinely **computed** alert from
request.pdhc's MDR-relevant path look like test data — the same error reversed,
and harder to notice.

Consumers: health 200, `/clinics` 401, `analysis-filter` 401 on POST, zero
error lines.

**Phase C content is complete.** All 17 euIPS sections are generated by
dedicated modules in obligation order. What remains is #797 (100-per-provider
batches, which moves the 40/150 baseline), then #798 (pin the nine consumers)
and #799 (the validator).

## 2026-10-07 — #797: 100 patients per provider, as an undoable batch

539 tests pass (522 + 17), same single pre-existing unrelated failure. 11 of
the 17 new tests fail against the untouched tree.

### The performance concern in the ticket does not materialise

Measured rather than assumed. ~19 resources per patient (min 9, median 19, max
29), so a 100-patient batch is **~2,220 rows — about 2.7× the entire live
database**, which holds 831. That sounded like a background job.

Timed: 5 patients 0.20s, 20 patients 0.29s, 50 patients 0.40s — roughly 1–4s
for 100. So no background job, and the ticket's suggestion to build one is
declined with a number rather than an opinion. **Caveat stated:** that timing is
SQLite, so it is indicative, not conclusive; the real check is a Postgres
round-trip in production.

### The purge, and the two traps in the delete order

Generating is the easy half; being able to undo it is what makes it usable
more than once. Two things about this schema make a naive purge wrong:

1. **`patient_index.fhir_resource_guid` -> `fhir_resources` cascades the OTHER
   way.** Deleting the Patient resource removes the PatientIndex, so resources
   must go after patients, not before.
2. **`fhir_resources.patient_guid` has no foreign key at all** (Rule 18, GUID
   references). Clinical resources are never cascaded, so a patients-only
   delete leaves every Condition, Observation and AllergyIntolerance
   orphaned, pointing at a patient that no longer exists.

### And a third trap the test caught: SQLite does not enforce FKs

The first version relied on the declared `ON DELETE CASCADE` for
`patient_clinic_assignments`, `ips_cards` and `ips_snapshots`. The test left
**8 of 8 assignments behind**.

The FKs do declare CASCADE and PostgreSQL honours them — but SQLite does not
enforce foreign keys unless `PRAGMA foreign_keys=ON`, and the test database is
SQLite. So the purge would have **worked in production and leaked in tests**:
the #730 shape exactly, a test engine behaving differently from the real one
and hiding the defect instead of showing it. Here it showed, because the test
asserted every table was empty rather than just the patients.

Every dependent is now deleted **explicitly**, deepest first, which is
identical on both engines and does not depend on FK enforcement being switched
on anywhere.

### Decisions recorded

* **Names are unique per BATCH, not globally.** `_build_unique_patient_pool`
  samples without replacement from 2400 combinations, so 100 is safe within one
  batch while two batches can repeat a name. Left that way deliberately — a
  simulator wants plausible Swedish names more than globally unique ones, and
  the batch guid is what distinguishes cohorts. A decision rather than a
  surprise.
* **No "purge the last one" and no "purge all".** The batch guid must be given
  explicitly, because either shortcut would make a mistake cheap to commit and
  expensive to notice. The page shows each batch's counts first, which is the
  same compare-then-write shape the deploy scripts use.
* **A patient with a NULL batch is unreachable by any purge**, with its own
  test. The 150 pre-existing production rows are NULL, which correctly means
  "not from a tracked batch", and a purge must not reach them.

### 2026-10-07 — #797 DEPLOYED, verified by a production round-trip

Live: `{"database":"connected","service":"ips-server","status":"ok"}`.
Backup `miserver:~/backups/predeploy/ips.pdhc/20261007T202329Z/`.

A real generate → verify → purge cycle against production Postgres, which is
the only thing that could answer the questions SQLite could not:

```
BASELINE        : 150 patients, 831 resources, 122 assignments, 40 cards, 41 snapshots
generate 5      : 0.12s  (0.023 s/patient -> ~2s for 100 on POSTGRES)
batch           : 5 patients, euIPS 5/5, 110 resources, clinic 1177
purge           : 0.11s
AFTER PURGE     : 150 / 831 / 122 / 40 / 41   -- baseline restored EXACTLY
batches remaining: 0
```

Three things this settles that nothing else could:

1. **The performance concern is closed on the real engine.** ~2s for 100
   patients on Postgres, not the background job the ticket proposed. Declined
   with a measurement rather than an opinion.
2. **The purge works where the FK semantics are real.** PostgreSQL honours the
   declared cascades, SQLite does not — the explicit deletes behave identically
   on both, and all five tables returned to their exact baseline rather than
   merely "about right".
3. **It leaves no residue.** 110 resources were written and removed; the
   database is bit-for-bit as it was. That is the shape to use for this kind of
   verification: a round-trip rather than test data left behind, or a
   measurement taken only on the test engine.

The route was driven in-process with `session["sso_user"]` set, which is all
the admin guard requires. Production auth configuration was not touched.

**Phase C is complete.** All 17 euIPS sections generate, 100 per provider works
as an identifiable undoable batch, and the pre-existing 150 rows remain
untouched with NULL batch guids — unreachable by any purge, which is the #789
fix-forward decision holding.

Remaining: #798 (pin the nine consumers) and #799 (the completeness validator).

## 2026-10-07 — #798: pin the consumers, and two corrections it forced

522+13 = 535 contract-relevant tests; full suite 552 pass with the one
pre-existing unrelated failure. `scripts/contract_check.py` runs green against
production: 10 routes registered, no `/api/v1/fhir` surface, and every pinned
shape verified against the real database.

### Correction 1: #788's consumer table was wrong

It was built by grepping endpoint PATHS without distinguishing the target
host, and it listed `/api/v1/fhir/Patient`, `/fhir/Observation` and
`/fhir/Condition` as ips endpoints with four consumers.

**ips has no `/api/v1/fhir/*` routes at all** — confirmed against the live URL
map. Those paths exist on the CDRs, which expose an identical FHIR surface, and
that is what analyse, dashboard, cdr and gateway read.

So **this ticket's own item 4 rests on a false premise.** It asked for a test
that #793's absent/unknown resources do not break `/fhir/Condition` for "the
four services that read them". No service reads those from ips, so the risk
does not exist and the test would have been theatre. What replaces it is a test
that ips still has NO fhir surface — because if one is ever added, the
absent/unknown resources become visible to whoever reads it, and that addition
needs its own thought.

Two other paths turned out not to be live calls: analyse's
`/api/v1/observations/search` goes to a CDR node, and
`/api/v1/blocks/check-bulk` appears only in a comment about a call #717
retired.

### Correction 2 — and a LIVE cross-service defect in contract.pdhc

`contract.pdhc/app/backend/app/signer_resolver.py::_resolve_patient` GETs
`{IPS_BASE_URL}/api/v1/patients/<guid>`. **ips has no such route.** Proved with
a real patient guid from the live database, from inside the contract container:

```
/api/v1/patients/4d91c614-…            -> 404   (route does not exist)
/api/v1/patients/4d91c614-…/clinics    -> 401   (route exists, auth-gated)
```

The 401 on the sibling path proves connectivity and base URL are fine; it is
specifically the bare patient route that is missing.

**And a second defect stacked on the same call:** `_ips_headers` sends the key
as `X-API-Key`. ips's `require_auth` reads **only** `Authorization`
(`Bearer …` or `ApiKey …`) and ignores `X-API-Key` silently — the trap already
recorded in memory as `infra_ips_auth_header_scheme` and the same one #730 hit.
So even with the route present, contract would get 401.

Impact: `STRICT_SIGNER_VALIDATION` **defaults to True** and is unset in
production, and `IPS_BASE_URL` is set (`http://host.docker.internal:9040`). So
in strict mode every contract carrying a `Patient/<guid>` signer reference is
rejected with "Patient/<guid> not found in IPS" — **for patients that
demonstrably exist**.

Why nobody noticed: contract's tests mock `http_requests.get` and return 200,
so they verify contract's handling of a success rather than whether the
endpoint exists. #704/#708's lesson precisely — real calls find what mocks
cannot.

Filed as its own ticket. Not fixed here: the fix is either in contract.pdhc or
a new additive route on ips, and that is a decision rather than a tidy-up.

### Three hollow checks in my own script, each caught by looking

1. **The shape checks silently skipped.** I set `session["sso_user"]`, which
   satisfies the admin blueprint but not `require_auth` — so all three shape
   checks 401'd and the script printed a clean run while verifying nothing.
2. **The #779 assertion skipped.** It picked any active patient; an unassigned
   one returns `[]` and there is no row to inspect. That assertion —
   `guid != organisation_guid` — is the single most valuable line in the file.
3. **The sim patient-dict assertion skipped.** It picked the alphabetically
   first clinic, which is "1177" with zero patients.

The recurring shape is worth naming: **a verification that depends on
incidental data silently verifies nothing.** The script now selects the rows
that exercise each assertion, and reports a skip in its notes rather than
passing quietly.

## 2026-10-07 — #799 DEPLOYED: the baseline, published

567 tests pass, same single pre-existing unrelated failure. Backup
`miserver:~/backups/predeploy/ips.pdhc/20261007T204809Z/`.
`scripts/contract_check.py` green in the same run: 0 failures.

### The baseline the ticket asked for, from production

```
150 patients
  all required sections present : 40  (27%)
  missing a required section    : 110
  no content in ANY section     : 110

REQUIRED      allergies / problems / medications    40 present, 110 missing
RECOMMENDED   immunisations / procedures / diag.    40 present, 110 missing
              devices                                0 present, 150 missing
OPTIONAL      all seven                              0 present, 150 missing
EU ADDITIONS  all three                              0 present, 150 missing
```

Two things this makes visible that the summary numbers did not:

* **`devices` is 0 / 0 / 150** — not 110. It confirms #794's finding from the
  other direction: the section never existed, so even the 40 patients with
  clinical data have none.
* **Every optional section and every EU addition is 0 / 0 / 150.** Nothing on
  this platform had ever generated a CarePlan, a Consent, a Flag, a travel
  history or a social history. The reform did not improve those sections; it
  created them.

### What the report refuses to say, and why that is the deliverable

It prints **"all required sections present"**, never "EU-conformant". Both
reasons are named in its own output: the EHDS implementing acts were not
confirmed adopted as of October 2026, and `CODES_VERIFIED` is False. A tool
that printed the second would hand someone a phrase to repeat in a technical
file, and #783 exists because this platform has already been bitten by a status
reported more confidently than it was known.

And a MISSING **recommended** or **optional** section is not a failure — #794's
conclusion, enforced here. Each obligation level is labelled in the output with
what MISSING means at that level, so the reader does not have to know. Failing
them would make a correct cohort look broken and train the reader to ignore the
output.

### The deploy bundle caught a path error of mine

`contract_check.py` was written to the repo-root `scripts/`, which holds local
deploy tooling and never enters the image — the Dockerfile's `COPY . .` runs
from `gateway/`. The bundle refused it as `MISSING-NEW` and aborted before
writing anything. Moved to `gateway/scripts/`, so it now runs as
`docker exec ips-app-1 python /app/scripts/contract_check.py` without a
`docker cp`.

### #881 (EPS B1) — the two EPS LOINC codes, 2026-11-02

`alerts` 104605-1 and `travel_history` 10182-4, from the EPS specification of
2026-10-30. Both notes record the provenance and that the source is a CI-build
of a STU 1 Ballot; a test pins that the provenance survives future edits.

`patient_provided` stays `None` by decision (#880 — EPS does not profile it, so
it is domestic), with a control test so a later "fill the empty ones" change
turns red.

`CODES_VERIFIED` unchanged: filling from a document is not verifying against
the published IG (#885).

**758 passed** (750 before). Controls: 3 / 2 / 6 red on deliberate breakage.

### #898 (EPS B8) — DeviceUsage, 2026-11-02

The service declared R5 and wrote the R4 resource name. Now writes
`DeviceUsage`; `LEGACY_RESOURCE_TYPES` accepts `DeviceUseStatement` on READ
only, normalised inside `section_matches()`, with the removal condition
documented beside it. The alias is kept out of `Section.resource_types`
because that tuple is served over the API and so describes what to write.

Two existing tests rewritten rather than deleted — including a narrative loop
that would have kept passing while checking nothing.

**772 passed** (758 before). Controls: 3 / 2 / 2 red on deliberate breakage.
Production row count for the old spelling still unmeasured; the accept-both
path makes it non-blocking.

### #883 (EPS B3) — Device and DeviceUsage visible to the API, 2026-11-02

Added to `SUPPORTED_RESOURCE_TYPES`; the CapabilityStatement follows
automatically. The gap was visibility, not existence — the resources were
already generated and already storable.

The feared patient-linkage bug did not exist: the create route already reads
`patient` as well as `subject`. Pinned with tests rather than patched.

`POST /fhir/DeviceUseStatement` stays refused: accept-both is for reading old
rows, not for admitting new ones.

Three R5 element-name questions recorded at the builder for #885 rather than
guessed (`Device.patient`, `DeviceUsage.subject`, `Device.code` in the absent
assertion).

**781 passed** (772 before). Controls: 7 / 2 red on deliberate breakage.

### #891 (EPS C4) — assignments can end, 2026-11-02

`ended_at` on `patient_clinic_assignments`, plus the partial unique index that
makes the history expressible: the old `(patient_guid, clinic_guid)` constraint
made "ended" terminal per pair, so a returning patient could not be
re-assigned.

One canonical rule (`active_only()`). The roster opts in; the three
AUTHORISATION sites (spärr, consents, care access) are deliberately HELD,
because flipping them is a tightening that needs its own verification. All ten
sites are inventoried in `CONSUMERS_OF_ASSIGNMENT` and two tests assert the
auth ones stay held.

Migration proven against real Postgres in a throwaway container: constraint
name looked up and dropped, partial index correct, re-run a no-op, closed+open
accepted, two open refused.

**792 passed** (781 before). Controls: 1 / 2 red.
**NOT deployed** — `add_assignment_ended_at.sql` must run on `ips-db-1`.

### #899(b) — spärr, consent and care access require an ACTIVE assignment, 2026-11-02

Narrowed through `active_only()`. Done while provably a no-op: `ended_at` is
NULL on all 296 production rows and nothing can set it, so the suite moved only
by the two #891 tests that asserted these paths were untouched — rewritten, not
deleted, since they are what stopped the flip being silent.

**802 passed** (792 before). Controls run per site: 1 red each. The third had
to be redone by hand after a regex revert broke the module — 8 ERRORs, not a
FAILURE, and a control that dies on an ImportError never ran.

Part (a), the write path that can actually end an assignment, is **#900**.

### #882 (EPS B2) — Patient Story and Patient History, 2026-11-02

Declared in `EPS_TEXT_SECTIONS`, deliberately NOT in `SECTIONS`: those two are
free text and no resource backs them, so PRESENT/ABSENT/MISSING cannot answer
for them, and a fourth status would break `euips_report`'s
"patient has nothing at all" check SILENTLY. Surfaced as DECLARED / NOT CARRIED
on `/euips-sections` and in the rendered report instead.

Narrative generation has no home yet: the euIPS path assembles no Composition.
It waits on #896 (EPS B7).

**813 passed** (802 before). Controls: 6 / 2 / 1 red — the middle one being the
guard against adding them to `SECTIONS`.

### #892 (EPS D1) — who consumes ips, pinned, 2026-11-02

`tools/pin_ips_consumers.py` + a committed baseline + 17 fixture checks.

**TEN consumers, not eleven.** `alert.pdhc` configures `IPS_BASE_URL` and
`IPS_API_KEY` and never calls — config keys nothing reads. And a hand count
could not have found `sim.pdhc`, which spells the key `IPS_PDHC_BASE_URL`;
`icd11.pdhc` has eight spellings. The tool discovers spellings rather than
taking a list.

Widening blocks (including config-only -> calls), narrowing informs. No sibling
names a path containing `ips` — the absence claim that makes #893's rename free
for cross-service calls.

**17 ok, 0 failed**, plus two live gate tests that exited 1 and left no residue.

### #895 (EPS C1) — the bitemporal state projection, 2026-11-02

`patient_state_facts`, derived from `fhir_resources` Patient versions and
`patient_clinic_assignments`. Both time axes; the record axis comes free from
the existing append-only write path. `valid_from` stays NULL where no FHIR
`period` exists, because inventing it from `recorded_at` is the single-axis
mistake this table exists to prevent.

The March/July case is tested and taught me something: FHIR versioning replaces
the whole resource, so "as known in August, where did they live in January?"
correctly returns nothing. I had asserted the opposite.

Verified against real Postgres as well as SQLite — the SQLite tz mismatch
corrupts the comparison, not just the assertion.

**829 passed** (813 before). Controls: 2 / 2 / 2 red.
**#901** carries the unwired half: no trigger, four sources missing, no route.

### #896 (EPS B7) — the export, 2026-11-02

`POST /api/v1/patients/export`, CSV or FHIR Bundle, selection-based.

On the API blueprint because the admin surface loads no user at all — measured,
and filed as #902. Scope is the same relationship spärr and consent use, with a
test asserting the set filter and the per-patient gate agree. Withheld patients
are absent rather than refused.

No personnummer in the CSV (#405); the Bundle carries it by design. Audit one
row per patient, and withheld patients are not audited. R5 only, tagged
`not-eps-conformant` in the document. 413 by name past the cap of 100.

**851 passed** (829 before). Controls: 4 / 1 / 1 / 2 red.

### #901 (EPS C1b) — the projection wired up, 2026-11-02

Trigger on `_sync_patient_index` (every Patient write) plus the three
assignment write sites; never raises into the write path. Four more sources
projected, and the per-source table is three findings rather than three
choices — `emergency_access` is the only source with genuinely distinct axes,
the two boolean opt-outs have NEITHER, and a block lift is its own fact.

`GET /api/v1/patients/<guid>/state?as_at=&as_known_on=`, scoped through the
export's filter rather than a third copy of the rule. 404 out of scope, not 403.

A real bug found by probing: guid columns return UUID objects and `json.dumps`
refuses them, so the insert died inside the flush naming the JSON encoder. All
projectors now coerce, and the test asserts the property not the fields.

**867 passed** (851 before). Controls: 3 / 1 / 4 / 6 / 1 red.
Dev Postgres is behind on `add_reform_patient_flags.sql` — noticed, not fixed.

### #900 (EPS C4c) — assignments can now be ended, 2026-11-02

`POST /patients/<g>/assignments` and `.../assignments/<clinic>/end`. Closes the
chain: #891 (schema), #899b (auth honours it), #901 (projection follows), and
now something can SET it.

`assign` refuses an open duplicate by name rather than letting the partial
unique index raise a 500. `end` accepts a backdated date — the ordinary case —
and refuses two things: an end before the start (an impossible fact) and a
FUTURE end (that would be an expiry, and #891 is explicit the two differ).

Who may change it is narrower than who may read: admin, or staff at the clinic
being changed.

**888 passed** (867 before). Controls: 6 / 2 / 2 / 1 red. `TestItMakes899Live`
asserts consent access goes True -> False across an end — the first time that
narrowing has had any effect.

### #886 (EPS B6) — alert implants as FHIR, 2026-11-02

`services/alert_implants.py`: a pure mapping from an alert implant assertion to
Device + DeviceUsage. No HTTP client, because alert.pdhc is deployed NOWHERE —
measured — and a client against it would be the xlate defect (#833). Transport
is **#903**.

The national term goes in `CodeableConcept.text`, because twelve codes in that
selection bind two or three terms and the code alone cannot say what the
clinician picked. `negation` maps to the section's absent code, so a mandatory
1..1 section reads EXPLICITLY_ABSENT rather than MISSING. `asserted_at`, never
`recorded_at`. Provenance survives on every path, including the negated one.

**906 passed** (888 before). Controls: 2 / 1 / 2 / 2 red.

### #888 (EPS C2) — addresses with periods, 2026-11-02

`patient_address()` with line, postalCode, city, country and an open-ended
`period`; telecom and RelatedPerson get one too, and the inline
`Patient.contact` mirror carries it so the two copies cannot disagree.

The payoff is asserted end to end: the state projection's address facts now
have a real `valid_from`, and an as-at read before the move excludes the
address while one after includes it.

A test of mine was a tautology (`A or <always true>`) and the control caught
it — the second time this session. **923 passed** (907 before).
Controls: 3 / 1 / 1 / 1 red.

## EPS C3 — #889 delivered (2026-11-02)

**990 passing**, from a 923 baseline: 923 + 67 new, and no other test outcome
moved. Three controls run, each failing on its own assertion with the import
verified first.

### The premise in #889 was wrong in both directions

#889 estimated 8–15 days because `care_access_policy` is "read by eleven
services", so a new branch meant eleven consumers.

**Cheaper:** a patient reading their own record never touches that module. It
answers a question whose every argument is a CARE identity; the patient surface
is gated by `require_patient`. `evaluate_care_access` has exactly two call
sites inside ips, both in `care_access_routes.py`. No new zone was needed and
the eleven consumers were untouched.

**More expensive, and this is the finding:** `require_patient` does not gate a
data surface, it gates the patient's self-determination controls. Ten of the
seventeen routes behind the patient identity are POST: create-block,
**lift-block**, extend-block, create-consent, revoke-consent, in both the JSON
and HTML surfaces. A relative admitted there without a method gate could lift
the patient's spärr and then read what it had been hiding — an escalation
chain, the same shape as #729 and #760, and forbidden outright by A3 (only the
patient may increase access; lifting a spärr increases access).

### What was built

- `PatientProxyGrant` beside `patient_consents`, with a validity interval
  carrying BOTH ends (so "while I am in hospital next month" is expressible)
  and revocation by either party.
- `evaluate_proxy_access` in `care_access_policy` with its own basis
  `patient_proxy` — a new AXIS, not a fourth zone. The existing zone rule is
  asserted untouched.
- `require_patient_or_proxy`: refuses every non-safe method **centrally**,
  because per-route is how one gets missed, plus `PROXY_RESERVED_ACTIONS` so a
  future scope widening cannot silently un-refuse the spärr controls.
- `require_proxy_self`: the one write a relative may make anywhere in ips is
  ending their own grant (A3 clause 4). A separate door that sets
  `g.proxy_user_guid` and never `g.patient_guid`, so a route behind it cannot
  reach the patient surface.
- The two patient-facing JSON read routes wired, so the chain is live rather
  than inert (#901's lesson).

### Things that needed care

- **The audit row must be COMMITTED.** Every other audit helper here does
  `add` + `flush` and lets the route's commit carry it. A proxy read is a GET
  and a GET commits nothing, so a flushed row is rolled back — visible in a
  fixture that shares the session, gone in production. Control 2 proved it.
- **Both denial codes, one response.** The audit distinguishes "never granted"
  from "no longer granted"; the HTTP response must not, or it confirms that
  this patient once named this person.
- **#890 corrected.** Its §5 put the grant in sso. #889 requires it beside
  `patient_consents`, so it is here, and sso carries identity only. ips's
  `AuditLog` already separates `actor_guid` from `patient_guid`, so the blob
  field #890 proposed turned out to be unnecessary.

### Honest limits

- The migration `gateway/migrations/add_patient_proxy_grants.sql` is **not
  applied to production**. It joins the two EPS migrations already waiting.
- The method gate is currently **redundant at the HTTP level**, because only
  GET routes are wired and the POST routes are still `@require_patient`, which
  refuses a relative blob outright. Control 1 showed exactly this: widening
  `PROXY_SAFE_METHODS` failed four policy tests and no HTTP test. The gate
  protects the next person who wires a POST route to the new decorator.
- The HTML portal (`patient_portal.py`, 10 routes) is untouched. What a proxy
  should SEE there — the lift and extend forms they cannot submit — is a UI
  decision, not this ticket.
- #889 asks for "a test per consuming service that an ungranted relative is
  refused". The refusal is asserted at ips's own boundary, in both the dev and
  the production auth path. The other consumers cannot be tested from this
  repo, and they are untouched because no zone changed.

## #902 — the admin surface gate (2026-11-02)

**1038 passing**, from 990. Four controls, each failing on its own assertion.

### The uncertainty the ticket was filed with is resolved: it WAS exposure

#902 deliberately stopped short of calling this a finding, because whether a
session-only gate is exposure depended on sso, which had not been measured.
Measured now, in code on both sides:

- `/api/auth/me/service` (`sso.pdhc/app/src/routes/auth.py:123`) authenticates
  the USER and authenticates the SERVICE, then builds the blob with **no check
  that this user may use this service**.
- sso has **no per-user service allowlist**. `allowed_services` lives on
  `Organisation`, for the machine/partner path only.
- ips's callback stored the returned blob on any 200 — and read `user_type`
  and `is_su_admin` into the session, which the gate then ignored.

So any authenticated platform user who completed ips's SSO login — **a patient
included** — had all 23 admin routes. Ten write; `/admin/mock-data/purge`
deletes patients, clinical resources and clinic assignments.

### Why it hid

The full suite passed **identically** before and after the gate was written:
990 both times. Not one test exercised it, because every test runs under
`AUTH_DISABLED`, where the gate returns immediately. A security gate with no
test is indistinguishable from no gate — so every meaningful check in
`test_admin_gate_902.py` runs with `AUTH_DISABLED` **off**.

### The deliberate split

CLAUDE.md §11's rule ships in two halves, because enforcing all of it blind
could lock legitimate users out of their own tool and who logs in is not
knowable from this repo:

1. **Unconditional:** not a professional and not an SU → refused. This cannot
   lock out a legitimate administrator, because no legitimate administrator of
   a patient registry is a patient.
2. **Shadow-logged:** the `"analysis"` phase requirement is evaluated and its
   would-be refusals logged at WARNING **naming the user**, but not enforced
   until `IPS_ADMIN_REQUIRE_ANALYSIS_PHASE` is set. Same shape as the
   platform's own `SSO_EMIT_LEGACY_BLOB_FIELDS` soak.

**The one decision left for the operator:** flip that flag once the shadow log
is quiet.

### Two bugs caught during the work

- **A redirect loop.** Sending a refused user to the SSO login page would log
  them in again and refuse them again, for ever. A missing session redirects; a
  refusal is a 403.
- **My gate read the wrong phase field.** It read only `effective_phases`,
  which is on sso's `LEGACY_BLOB_FIELDS` kill-switch list (#409) and staged to
  stop being emitted. dashboard, rosetta and cdr all read
  `session_phases or effective_phases` (#415/#416/#417). Left alone, this gate
  would have seen an empty phase list the day #409's flag flips and refused
  every professional on the platform. Caught by comparing against the three
  siblings, not by a test — and now tested, with the ordering asserted rather
  than a union.

### The substring exemption

The old gate read `if "download" in request.endpoint: return None` — four doc
downloads today, and **any** future endpoint whose name contains "download".
Now an explicit set. Tested behaviourally by driving the gate with a crafted
endpoint name, because asserting the set's contents proves only that the set is
narrow, not that the gate consults it.

### Step 4, recorded as a decision rather than an omission

`/admin/patients` stays **unscoped**: an admin tool that lists every patient is
the point of an admin tool, now that only professionals and SUs reach it. Noted
rather than left silent, which is what #902 asked for. Org scoping would also
be unverifiable against the current population — all assigned ips patients sit
in one organisation.

## #903 — EPS B6b, the receiving half (2026-11-02)

**1088 passing**, from 1038. Seven controls across two files, each failing on
its own assertion.

### Step 1 was a decision and the operator took it

alert.pdhc runs nowhere — re-confirmed. The operator's decision: **build the
receiver now, deploy later.** That is safe in a way a client would not be: a
receiver names no URL and invents no default, so the xlate defect (#833) — a
module-level base URL manufacturing a configured-looking service out of an
unset variable, turning a permanent condition into a retryable one — cannot
arise. The endpoint is inert until something calls it.

### The real blocker for step 3 was a decorative column

Step 3 asked for a key "scoped to the one route and nothing else". ips has no
`KNOWN_SERVICES` and does not need one: `ApiKey.scopes` has existed since the
model was written. It is SET at mint time (`api/auth_routes.py:31`) and COPIED
on rotation (`:89`), and it was read **nowhere**.

So every API key in ips reached every `@require_auth` route — the whole FHIR
surface, patients, blocks, consents, state, export — whatever it was issued
for. The #729 shape (a field that looks like a gate and gates nothing)
producing the #760 consequence (a credential issued for one purpose reaching
everything). A key minted by a logged-in user also carries that user's guid, so
it inherits their privileges in full: a key minted by an SU is an SU key.

`require_scope()` is **opt-in per route**, deliberately. Requiring every key to
carry a scope would break every key already issued — the same lockout risk as
#902's phase gate. A route that declares nothing behaves exactly as before, and
that is asserted in both directions, because "additive" is a claim about the
routes NOT changed and is otherwise untested.

An SSO caller is refused on a scoped route even as an SU: a scoped route exists
for a machine, and admitting a human identity is how a service surface quietly
becomes a general one. An SU who needs to drive it by hand mints a key.

### Idempotence without a second source of truth

The natural key is (patient, code_system, code, national_term, asserted_at).
`(code_system, code)` alone is **not** a key — twelve codes in this selection
bind two or three national terms, the same fact that put the term in
`CodeableConcept.text` in #886.

Rather than a receipts table, the resource ids are UUIDv5-derived from that key.
`alert_implants.to_fhir` already takes `device_id`/`usage_id` precisely so "the
caller controls identity", so idempotence is a lookup on
`FhirResource.resource_id` and there is nothing to drift. The namespace UUID
must never change: doing so would make every pushed assertion look new.

### Three of my own test weaknesses, recorded

- A test **skipped in isolation** and only "passed" because another test had
  registered its probe route first. A test that passes by not running is worse
  than no test.
- Registering probe routes on the session-scoped app produced **13 errors**
  when the whole suite ran — Flask refuses `route` after the first request.
  Both were fixed by dispatching the decorated view inside a request context
  instead, which also removed the ordering.
- A test claimed the `isinstance` guard stops a string matching "by
  substring". Wrong: iterating a string yields characters, so a string denied
  either way, and the control that removed the guard failed nothing — which is
  how the error was found. Parametrising it showed the guard does carry
  behaviour, just not that one: without it a non-iterable value raises inside
  the gate and the caller gets a 500 instead of a 403. The comment now says
  what the control showed.

### Handover when alert is deployed

1. Mint an API key with `scopes: ["implants:write"]` and nothing else.
2. Set it as alert's `IPS_API_KEY`, with `IPS_BASE_URL=https://ips.pdhc.se`
   (the public subdomain, not a loopback — alert needs no subdomain of its own,
   only outbound access).
3. alert POSTs batches of up to 500 assertions to
   `/api/v1/implants/assertions` and may retry freely; a re-push is counted as
   a duplicate and creates nothing.

## #893 — EPS D2: decided NOT to rename (2026-11-02)

**1096 passing**, from 1088. Three controls, each failing on its own assertion.

### The decision

The service is not renamed. Recorded in `plans/eps_state_reform.md` §1 so it
is a decision rather than a ticket nobody closed.

### #893 was wrong about one of its three hazards

It reported `COMPOSE_PROJECT_NAME` as "not pinned anywhere in this repo —
verified, no occurrence in any .yml, .sh, .env* or .md". The verification is
accurate and the conclusion is not: the project name **is** pinned, by
`name: ips` on line 1 of `gateway/docker-compose.yml`, Compose v2's own project
key. That is why the live containers are `ips-app-1` / `ips-db-1` and not
`ipspdhc-*` — and the hyphens are themselves evidence that production runs
Compose v2, since v1 named containers with underscores.

The grep looked for the VARIABLE and missed the KEY that does the same job.

### The hazard, correctly stated — and it is real

Measured with a throwaway compose file: `COMPOSE_PROJECT_NAME` in the
environment **overrides** `name:` in the file. So the risk was never an
unpinned project; it is that the variable, if ever set, silently wins, and a
blank nobody filled is a blank somebody can fill wrongly — which is exactly how
dashboard's project became `current` (#113). The value is now in
`.env.example` as well and a test asserts the two **agree**, because two pins
that can disagree are worse than one.

The external volume is guarded too. `pgdata` is `name: ips_pgdata,
external: true`, which #893 calls "the good luck"; a test makes it something
other than luck, since dropping `external: true` hands the production data to
compose.

### The recommended alternative is blocked, and that needed saying

#893 recommends "add EPS as a declared capability instead". Measured, the EPS
surface is two inspection routes (`euips-header`, `euips-sections`); the
CapabilityStatement declares the IPS `$summary` operation and there is **no EPS
equivalent**. So `eps` was deliberately NOT added: declaring it would advertise
a capability that is not there, which is #804 in the one document whose whole
job is telling a consumer what this server can do. That declaration belongs in
the same change as **EPS B4**, the endpoint it would describe.

Net position: do neither for now. Weaker than #893 implies, and better stated
than implied.

### The cost recounted, and it doubled

| | #893 | recounted |
|---|---|---|
| occurrences | ~411 | **832** |
| directories | 15 | **19** |
| ips.pdhc itself | 91 | **193** |

Four directories were missing from the original list entirely: `results`,
`css_instrux`, `tools` and `pdhc` (the website, 69 occurrences). Part of the
rest is this repo's own growth through the EPS work.

The direction matters more than the figure: a cost estimate that drifts upward
while the work is deferred is an estimate that will keep justifying the
deferral. Worth knowing that is what is happening.

## #885 — EPS B5: the codes verified (2026-11-02)

**1136 passing** (+1 deliberate skip), from 1096. Five controls, each failing
on its own assertion.

### What was fetched

| guide | version | what was checked |
|---|---|---|
| HL7 Europe EPS `composition-eu-eps` | 1.0.0-ballot (ci-build 150), 2026-06-06, **R4** | all 17 section slices, codes + cardinalities, `Composition.type` |
| HL7 IPS `absent-unknown-uv-ips` | 1.1.0 (STU 1 Update 1) | the CodeSystem URL and all six absent codes |
| HL7 FHIR **R5** `device` / `deviceusage` | R5 | the three element names `euips_recommended` nominated |
| HL7 Europe `observation-travel-eu-eps` | same ballot | the travel-history Observation code |

### Result: every section code is correct

All 16 LOINC section codes, `Composition.type` 60591-5, the absent/unknown
CodeSystem URL and all six absent codes match the published guides.

### Four disagreements, none of them a wrong section code

1. **EPS makes 47519-4 and 46264-8 `1..1`**; both are RECOMMENDED here.
   `Composition.section` is 5..* and those two are the fourth and fifth. NOT
   changed — `obligation` drives `conformant` and the mock generator, and this
   catalogue also serves domestic IPS where both are recommended. **#906.**
2. **EPS has no 11348-0 section at all.** `EPS_TEXT_SECTIONS`'s note on 11329-0
   had already anticipated it ("once 11348-0 is unprofiled") and #880 decided
   resolved conditions stay domestic. The fetch turned an expectation into a
   measurement.
3. **The three device element names are all three wrong against R5** — exactly
   as the module suspected. R5 Device has no `patient`; `DeviceUsage.patient`
   is 1..1 while R4's `subject` is *Deleted*; Device has `type` and no `code`.
   **#907**, not fixed here, because removing `Device.patient` removes the only
   patient linkage in the JSON and that needs a decision.
4. **The travel code was wrong and is FIXED.** #796 chose SNOMED `420008001`
   provisionally and said so; the EPS profile FIXES `Observation.code` to LOINC
   **94651-7**. The old code stays in the MATCH set, so rows stored before
   today do not silently turn the section from PRESENT back to MISSING. The
   profile's `value[x]` binding is also REQUIRED (ISO 3166-1-2), so the
   destination is now a coded country rather than `valueString: "Thailand"`,
   which satisfied nothing.

Marking that code provisional is what made it findable. **A guess marked
provisional invites checking; a guess the flag now calls "verified" does not.**

### What deliberately stays unverified

`euips_header.CODES_VERIFIED` is **still False**, and not from neglect: its
scope includes R5 element shapes, and an R4 guide cannot verify an R5 shape.
A test asserts, by parsing the module, that it defines its own literal flag and
does not import the sections module's.

### Verified codes are not conformance

The EPS guide is a ballot whose own pages say it is not an authorized
publication; it is R4 while this platform is R5; cardinality was not checked.
#799's rule is unchanged. The DISCLAIMER was rewritten rather than trimmed —
one of its two reasons changed (ballot status replaces "codes unverified"),
because dropping to a single reason would make the refusal look like it rested
on the EHDS timetable alone.

Leaving "not yet verified" in that string would have been the #848 failure:
a status line nobody updated, which sent a session to redo finished work.

### Two of my own weaknesses

- I cited **#906** in a docstring *before filing it*. It happened to land on
  906. That is luck, and it is the third lesson in CLAUDE.md §2 — file the
  ticket before citing it.
- A test asserted `header.CODES_VERIFIED is not sections.CODES_VERIFIED` to
  guard against aliasing. It cannot: Python interns booleans, so it only ever
  restated "their values differ". Replaced with an `ast` parse of the module.
  The first replacement also failed, because this module mentions
  `euips_sections` in a comment — a substring test was the wrong instrument
  twice before the right one.

## #906 — two profiles, one catalogue (2026-11-02)

**1164 passing**, from 1136. Four controls, each failing on its own assertion.

### The design decision, and why the disruptive option was right

`is_conformant(status, *, profile)` has **no default**. A default would have
been less disruptive and much worse: the failure mode worth preventing is not
a wrong answer, it is a caller who never noticed there were two questions and
silently received the other one's answer — and a default protects precisely the
callers written before the second profile existed, which are the ones nobody
has reviewed for it.

Making it mandatory broke **ten** call sites. Three were making a claim that was
true of one profile and false of the other, and one test had to be split:
`test_a_missing_recommended_section_does_not_break_conformance` is an IPS
statement, and under EPS a missing recommended section is exactly what breaks
conformance. The unqualified sentence was half wrong.

### `obligation_eps` is set only where it differs

None means "the same", so a reader finds the two divergences instead of
comparing seventeen identical pairs. A test asserts every other section leaves
it None, so the convention cannot erode.

### The cross-check the ticket asked for, and it works

`Composition.section` is **5..\*** in the published profile, and
`required_keys(PROFILE_EPS)` returns exactly 5. That single number is what
catches a future ballot adding a sixth required section — a change every
code-by-code comparison would pass, because every code it checked would still
be right. Verified by control: marking a third section EPS-required fails
`test_THE_CROSS_CHECK_eps_required_count_matches_the_published_5` by name.

### What each surface now answers

| surface | profile | why |
|---|---|---|
| `/euips-sections` | **both** | a diagnostic surface should report, not choose on its caller's behalf. `conformant` keeps its IPS value and gains `conformant_profile`; `conformance` carries both. |
| `euips_report` | **both** | "how far are we from EPS?" is the question a platform report exists to answer, and it is not derivable from the IPS figure. |
| `mock_generator` | IPS | it writes the three IPS required sections; procedures and devices have age gates, so generating them for everyone would make implausible patients. An EPS-complete cohort is a separate decision, not a default. |
| `euips_batch` | IPS | counts a batch against the surface the generator writes for. |

### Two small things worth keeping

- `required_keys` RAISES on an unknown profile rather than returning `()`. An
  empty required set makes every patient conformant, which is the one wrong
  answer that looks like good news.
- EPS makes the sections 1..1; it does not make them non-empty. An explicit
  "no known devices" satisfies EPS, which is the whole reason the absent codes
  exist — asserted, because reading 1..1 as "must have content" is the obvious
  mistake.
