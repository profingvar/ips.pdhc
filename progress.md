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
