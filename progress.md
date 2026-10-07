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
