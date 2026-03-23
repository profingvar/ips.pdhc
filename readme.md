# IPS Server (FHIR R5) — Deployment Plan

Patient-Driven Healthcare (PDHC) International Patient Summary service. Flask + PostgreSQL, Dockerised, FHIR R5 compliant.

**Ports:** 9040 (API), 9041 (PostgreSQL), 9042 (Admin UI)
**App folder:** `gateway/`
**Subdomain:** `ips.pdhc.se`

---

## 1) Project scaffolding and configuration

### 1.a Create folder structure

```
gateway/
  app/
    __init__.py          # Flask app factory
    config.py            # Configuration from .env
    models/              # SQLAlchemy models
    api/                 # Application API blueprints (/api/v1/...)
    fhir/                # FHIR API blueprints (/fhir/...)
    services/            # Business logic (IPS generation, auth, etc.)
    templates/           # Jinja2 templates (admin UI)
  static/
    css/
      pdhc.css           # Design system stylesheet
  migrations/            # Alembic migration versions
  tests/                 # pytest test suite
  requirements.txt
  Dockerfile
  docker-compose.yml
  .env.example
  start.sh
  alembic.ini
```

### 1.b Create `.env.example` and `config.py`

Environment variables:

| Variable | Example | Purpose |
|----------|---------|---------|
| `FLASK_ENV` | `development` | Flask mode |
| `SECRET_KEY` | `(generated)` | Flask session/signing key |
| `DATABASE_URL` | `postgresql+psycopg://ips_user:pass@localhost:9041/ips_db` | DB connection |
| `POSTGRES_USER` | `ips_user` | Docker PG user |
| `POSTGRES_PASSWORD` | `(generated)` | Docker PG password |
| `POSTGRES_DB` | `ips_db` | Docker PG database |
| `OAUTH_BASE_URL` | `https://sso.pdhc.se` | SSO service base URL |
| `API_KEY_SECRET` | `(generated)` | Fernet key for encrypting push destination credentials |
| `BOOTSTRAP_SU_USERNAME` | `admin` | Initial superuser |
| `BOOTSTRAP_SU_PASSWORD` | `(generated)` | Initial superuser password (remove after first login) |
| `CORS_ORIGINS` | `http://localhost:9042` | Allowed CORS origins |
| `AUTH_DISABLED` | `true` | Disable auth for local dev (set `false` in prod) |
| `APP_PORT` | `9040` | Flask listen port |
| `ADMIN_PORT` | `9042` | Admin UI port |

### 1.c Create `requirements.txt`

### 1.d Create `Dockerfile` and `docker-compose.yml`

### 1.e Create `start.sh` (Rule 16)

Single script: kill ports 9040–9043, activate venv, start Docker (DB), start Flask app. Ctrl+C graceful shutdown.

### 1.f Copy `pdhc.css` into `gateway/static/css/`

### 1.g Create `CLAUDE.md` in project root

---

## 2) Database models (SQLAlchemy + Alembic)

### 2.a Define SQLAlchemy models from `initial_sql_design.txt`

Models: `User`, `Clinic`, `UserClinicAssignment`, `ApiKey`, `FhirResource`, `PatientIndex`, `PatientClinicAssignment`, `IpsCard`, `IpsSnapshot`, `PushDestination`, `PushJob`, `AuditLog`, `CapabilityStatement`.

### 2.b Initialise Alembic and create initial migration

### 2.c Write bootstrap superuser logic

On first startup, if `BOOTSTRAP_SU_USERNAME` and `BOOTSTRAP_SU_PASSWORD` are set and no users exist, create the superuser. Log the event.

### 2.d Write tests for models and bootstrap

---

## 3) Authentication and authorisation

### 3.a Implement SSO token validation middleware

Resolve Bearer token via `OAUTH_BASE_URL/api/auth/me`. Attach resolved user to `g.current_user`. Fail closed on error.

### 3.b Implement API key validation

Hash incoming key, look up in `api_keys`, check `is_active`, `expires_at`, `revoked_at`. Update `last_used_at`.

### 3.c Implement `AUTH_DISABLED` bypass for development

When `AUTH_DISABLED=true`, attach a synthetic dev user to context. Never allow in production.

### 3.d Whitelist health/metrics endpoints from auth

### 3.e Write tests for auth flows

---

## 4) FHIR REST surface (`/fhir/...`)

### 4.a Implement FHIR CapabilityStatement endpoint

`GET /fhir/metadata` — returns the server's CapabilityStatement (FHIR R5).

### 4.b Implement Patient CRUD

- `POST /fhir/Patient` — create
- `GET /fhir/Patient/<id>` — read
- `PUT /fhir/Patient/<id>` — update
- `GET /fhir/Patient` — search (by identifier, name, birthdate)

Sync `patient_index` on create/update.

### 4.c Implement clinical resource CRUD

Generic endpoints for: `Condition`, `Observation`, `MedicationStatement`, `AllergyIntolerance`, `Immunization`, `Procedure`, `DocumentReference`, `DiagnosticReport`.

- `POST /fhir/<ResourceType>`
- `GET /fhir/<ResourceType>/<id>`
- `GET /fhir/<ResourceType>?patient=<patient_id>`

### 4.d Implement `$ips` operation

`GET /fhir/Patient/<id>/$ips` — generate IPS Bundle on demand (FHIR R5 profile).

### 4.e Implement FHIR error handling (OperationOutcome)

### 4.f Write tests for FHIR endpoints

---

## 5) Application API (`/api/v1/...`)

### 5.a Health and metrics endpoints

- `GET /api/v1/health` — uptime, DB connectivity check
- `GET /api/v1/metrics` — resource counts, recent activity stats

### 5.b IPS card management

- `POST /api/v1/ips/cards` — create card for a patient
- `GET /api/v1/ips/cards` — list cards (filterable by patient, clinic)
- `GET /api/v1/ips/cards/<guid>` — get card detail
- `PATCH /api/v1/ips/cards/<guid>` — update (status, mode)
- `DELETE /api/v1/ips/cards/<guid>` — archive card

### 5.c IPS snapshot management

- `POST /api/v1/ips/cards/<guid>/snapshots` — generate and store snapshot
- `GET /api/v1/ips/cards/<guid>/snapshots` — list snapshots for card
- `GET /api/v1/ips/snapshots/<guid>` — get snapshot metadata
- `GET /api/v1/ips/snapshots/<guid>/bundle` — get full bundle JSON (audited)

### 5.d Push destination management

- `POST /api/v1/push/destinations` — create destination
- `GET /api/v1/push/destinations` — list destinations
- `GET /api/v1/push/destinations/<guid>` — get destination
- `PATCH /api/v1/push/destinations/<guid>` — update
- `DELETE /api/v1/push/destinations/<guid>` — deactivate

### 5.e Push job management

- `POST /api/v1/push/jobs` — create push job (snapshot + destination)
- `GET /api/v1/push/jobs` — list jobs (filterable by status)
- `GET /api/v1/push/jobs/<guid>` — get job status

### 5.f API key management

- `POST /api/v1/auth/keys` — create key (returns plaintext once)
- `GET /api/v1/auth/keys` — list keys (prefix + metadata only)
- `DELETE /api/v1/auth/keys/<guid>` — revoke key
- `POST /api/v1/auth/keys/<guid>/rotate` — rotate (revoke old, create new)

### 5.g Audit log endpoint

- `GET /api/v1/audit` — query audit events (by actor, patient, event_type, date range)

### 5.h Clinic management

- `POST /api/v1/clinics` — create clinic
- `GET /api/v1/clinics` — list clinics
- `GET /api/v1/clinics/<guid>` — get clinic
- `PATCH /api/v1/clinics/<guid>` — update

### 5.i Write tests for all application API endpoints

---

## 6) IPS generation service

### 6.a Implement IPS Bundle builder

Deterministic transformation: patient → collect resources → assemble Bundle with Composition, referenced entries, and IPS profile metadata.

### 6.b Implement full vs minimal mode

- **Full:** all clinical resource types
- **Minimal:** conditions + medications + allergies only

### 6.c FHIR R5 profile compliance validation

Validate generated Bundle against IPS profile canonical URL. Ensure reference integrity and required sections.

### 6.d Write tests for IPS generation (both modes)

---

## 7) Audit service

### 7.a Implement audit event creation

Utility to log events with actor, patient, event type, request context. Called from route handlers.

### 7.b Audit sensitive reads

Specifically audit: snapshot bundle retrieval, patient data access, API key operations.

### 7.c Write tests for audit logging

---

## 8) Admin UI (port 9042)

### 8.a Create `base.html` extending PDHC design system

### 8.b Dashboard page

Service status, resource counts, recent audit events.

### 8.c Patient browser

Search and view patients, their resources, cards, and snapshots.

### 8.d Push job monitor

View push job queue, statuses, errors.

### 8.e Write tests for admin UI routes

---

## 9) Docker and deployment

### 9.a Finalise Dockerfile (multi-stage if needed)

### 9.b Finalise `docker-compose.yml`

Services: `db` (PostgreSQL 16 on port 9041), `app` (Flask on port 9040).

### 9.c Create `.env.example` with all variables documented

### 9.d Write `start.sh` with full lifecycle (Rule 16)

### 9.e Test full Docker Compose stack locally

---

## 10) API endpoint test script (Rules 9, 20)

### 10.a Create `tests/test_api_endpoints.py`

Comprehensive pytest script testing all endpoints against the capability statement. Covers FHIR and application API.

### 10.b Create `tests/test_fhir_compliance.py`

Validate FHIR R5 resource structure, OperationOutcome format, Bundle profile.

### 10.c Run full test suite; store results in `./results/<timestamp>_results/`

---

## 11) API key procedures (Rule 8)

### Suggested rules

1. **Storage:** keys are hashed (SHA-256) before persistence. Plaintext is displayed exactly once at creation and never stored.
2. **Rotation:** keys can be rotated via `/api/v1/auth/keys/<guid>/rotate`. Old key is revoked immediately; new key is returned.
3. **Expiry:** keys may have an `expires_at` timestamp. Expired keys are rejected at validation time. Default expiry: 90 days (configurable).
4. **Revocation:** keys can be revoked via `DELETE /api/v1/auth/keys/<guid>`. Revocation is immediate and irreversible.
5. **Audit:** all key operations (create, rotate, revoke) are logged in the audit trail.
6. **Scope:** keys carry scopes (e.g. `read:fhir`, `write:fhir`, `admin`). Endpoint access is checked against key scopes.

### Maintenance procedures

- Review active keys monthly. Revoke unused keys (no `last_used_at` in 30+ days).
- Rotate all service-account keys at least every 90 days.
- After a security incident: revoke all keys, issue new ones.

---

## 12) Server deployment (Mac Mini)

### 12.a Package for deployment

Follow the generic procedure in `../css_instrux/pointers_for_serversetup.md`:
- Tarball excluding venv, .env, __pycache__, results
- Copy to server via operator

### 12.b Server setup

- Unpack to `/usr/local/www/ips.pdhc/`
- Create `.env` with production credentials
- `docker-compose up -d`

### 12.c Nginx reverse proxy

- Config at `sites-available/ips.pdhc.se.conf`
- Proxy to `127.0.0.1:9040`
- SSL via Let's Encrypt

### 12.d Port allocation update

| Project | App Port | DB Port | Admin Port | Subdomain |
|---------|----------|---------|------------|-----------|
| plan.pdhc | 9030 | 9031 | — | plan.pdhc.se |
| forms.pdhc | 9036 | 9037 | — | forms.pdhc.se |
| **ips.pdhc** | **9040** | **9041** | **9042** | **ips.pdhc.se** |

### 12.e Verify bootstrap SU, then remove password from `.env`
