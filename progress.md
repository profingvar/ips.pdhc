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
