# IPS Server — Changed Files Log

All edited files with full paths, updated after each change.

---

| File | Action | Step |
|------|--------|------|
| `ips.pdhc/initial_sql_design.txt` | created | pre-plan |
| `ips.pdhc/readme.md` | created | pre-plan |
| `ips.pdhc/progress.md` | created | pre-plan |
| `ips.pdhc/changed_files.md` | created | pre-plan |
| `ips.pdhc/CLAUDE.md` | created | 1.g |
| `gateway/app/__init__.py` | created | 1.a |
| `gateway/app/config.py` | created | 1.b |
| `gateway/app/admin.py` | created | 8.a |
| `gateway/app/models/__init__.py` | created | 2.a |
| `gateway/app/models/base.py` | created | 2.a |
| `gateway/app/models/user.py` | created | 2.a |
| `gateway/app/models/clinic.py` | created | 2.a |
| `gateway/app/models/api_key.py` | created | 2.a |
| `gateway/app/models/fhir_resource.py` | created | 2.a |
| `gateway/app/models/patient_index.py` | created | 2.a |
| `gateway/app/models/ips_card.py` | created | 2.a |
| `gateway/app/models/ips_snapshot.py` | created | 2.a |
| `gateway/app/models/push_destination.py` | created | 2.a |
| `gateway/app/models/push_job.py` | created | 2.a |
| `gateway/app/models/audit_log.py` | created | 2.a |
| `gateway/app/models/capability_statement.py` | created | 2.a |
| `gateway/app/services/__init__.py` | created | 3.a |
| `gateway/app/services/auth_service.py` | created | 3.a |
| `gateway/app/services/bootstrap_service.py` | created | 2.c |
| `gateway/app/services/audit_service.py` | created | 7.a |
| `gateway/app/services/ips_generator.py` | created | 6.a |
| `gateway/app/services/fhir_service.py` | created | 4.b |
| `gateway/app/api/__init__.py` | created | 5.a |
| `gateway/app/api/health.py` | created | 5.a |
| `gateway/app/api/ips_routes.py` | created | 5.b |
| `gateway/app/api/push_routes.py` | created | 5.d |
| `gateway/app/api/auth_routes.py` | created | 5.f |
| `gateway/app/api/audit_routes.py` | created | 5.g |
| `gateway/app/api/clinic_routes.py` | created | 5.h |
| `gateway/app/fhir/__init__.py` | created | 4.a |
| `gateway/app/fhir/fhir_routes.py` | created | 4.a |
| `gateway/app/templates/base.html` | created | 8.a |
| `gateway/app/templates/dashboard.html` | created | 8.b |
| `gateway/wsgi.py` | created | 1.a |
| `gateway/requirements.txt` | created | 1.c |
| `gateway/.env.example` | created | 1.b |
| `gateway/Dockerfile` | created | 1.d |
| `gateway/docker-compose.yml` | created | 1.d |
| `gateway/alembic.ini` | created | 2.b |
| `gateway/migrations/env.py` | created | 2.b |
| `gateway/migrations/script.py.mako` | created | 2.b |
| `gateway/start.sh` | created | 1.e |
| `gateway/static/css/pdhc.css` | copied | 1.f |
| `gateway/tests/__init__.py` | created | 2.d |
| `gateway/tests/conftest.py` | created | 2.d |
| `gateway/tests/test_models.py` | created | 2.d |
| `gateway/tests/test_health.py` | created | 5.a |
| `gateway/tests/test_fhir_endpoints.py` | created | 4.f |
| `gateway/tests/test_app_api.py` | created | 5.i |
| `gateway/tests/test_api_endpoints.py` | created | 10.a |
| `gateway/app/templates/base.html` | updated | 8.c |
| `gateway/app/templates/patients.html` | created | 8.c |
| `gateway/app/templates/patient_detail.html` | created | 8.c |
| `gateway/app/templates/push_monitor.html` | created | 8.d |
| `gateway/app/admin.py` | updated | 8.c–8.d |
| `gateway/tests/test_admin.py` | created | 8.e |
| `gateway/server_configs/ips.pdhc.se.conf` | created | 12.c |
| `gateway/server_configs/deploy.md` | created | 12.a |
| `gateway/app/templates/docs_base.html` | created | 8.f |
| `gateway/app/templates/docs_index.html` | created | 8.f |
| `gateway/app/templates/docs_api.html` | created | 8.f |
| `gateway/app/templates/docs_capability.html` | created | 8.f |
| `gateway/app/templates/docs_manual.html` | created | 8.f |
| `gateway/app/templates/docs_technical.html` | created | 8.f |
| `gateway/app/admin.py` | updated | 8.f |
| `gateway/app/templates/base.html` | updated | 8.f |
| `gateway/tests/test_admin.py` | updated | 8.f |
| `ips.pdhc/progress.md` | updated | 8.f |
| `ips.pdhc/changed_files.md` | updated | 8.f |
| `gateway/app/services/auth_service.py` | Ticket #53 — added `_must_change_password_response()` helper returning a FHIR 403 OperationOutcome with `{OAUTH_BASE_URL}/change-password` in `details.text`; `require_auth` Bearer branch gates on it after `resolve_sso_user()` succeeds. require_auth guards API+FHIR routes (admin blueprint has its own `before_request`), so the redirect vs 403 split from the ticket collapses to 403 here. Deployed to `/usr/local/www/pdhcips/gateway/app/services/auth_service.py`; backup `.bak-2026-04-15T18-46-29Z` on server. Gunicorn master pid 1243 HUPed; `https://ips.pdhc.se/api/v1/health` returns 200. |
- 2026-04-16: gateway/app/api/health.py — ticket #70 adds Access-Control-Allow-Origin https://www.pdhc.se + Methods GET + Vary: Origin + Cache-Control: no-store so services.html can use mode:'cors'.
- 2026-04-16: gateway/app/admin.py + gateway/app/templates/base.html + gateway/app/templates/patients.html + pdhcips/gateway/app/templates/base.html — ticket #78 reconcile (ips): pushed LOCAL→SERVER for all 4 conflicts. Local was ahead by a coherent feature set that never deployed: (1) `admin.py` — pulls `managingOrganization` from FHIR Patient and sets `p.organisation` on patients list; patient-create form now accepts `clinic_guid` and writes `managingOrganization` into the FHIR Patient resource; (2) `base.html` (both copies) — adds "PDHC / IPS Server" breadcrumb nav linking back to www.pdhc.se/services.html; (3) `patients.html` — adds Organisation column + clinic dropdown in create form. Verified the `clinics` table and `Clinic` model already exist on server (prod DB has 13 tables incl. `clinics`). Gunicorn master pid 1243 SIGHUP'd; workers 20379/20380 booted clean, no import errors. Server backups at `/tmp/ips_*.server.bak.20260416T202949Z.*`.
- 2026-05-02: gateway/app/templates/docs_technical.html + gateway/app/templates/docs_manual.html — refreshed /admin/docs against current state. **docs_technical.html**: "Docker Services" table replaced with a "Runtime topology" table — only the DB runs in Docker (`ips-db-1` in the shared Colima VM); the app is bare-metal Flask+gunicorn on `127.0.0.1:9040` (started by `start.sh` via `python wsgi.py` in dev or `gunicorn --bind 127.0.0.1:9040` in prod). Added the rationale that copying a venv across releases silently glues a new release to the old one. Port-allocation table reduced from a partial multi-service grid to just the 904x block ips.pdhc owns. Test-suite count corrected `158 tests / 6 files` → `148 test methods / 7 test files` with filenames listed. **docs_manual.html**: Admin UI auth corrected — was "no separate auth when accessed through the same host", actually gated by sso.pdhc and redirects unauthenticated callers to SSO login then back to `/callback`. Restart procedure replaced with separate app-only / db-only flows that match the bare-metal-app + dockerised-db split (`kill -TERM $(cat ~/.gunicorn/ips.pid)` + `./start.sh` for the app; `colima ssh -- docker restart ips-db-1` for the db). Note added that `docker restart ips-db-1` keeps create-time env so a `.env` change needs `docker-compose -p pdhcips up -d db` instead. Backup command updated to use `docker exec ips-db-1 pg_dump … --format=custom`. Log-viewing flipped from `docker-compose logs` to `tail -f ~/.gunicorn/ips.{access,error}.log` (app) + `colima ssh -- docker logs -f ips-db-1` (db). Deployed to live path `/usr/local/www/pdhcips/gateway/app/templates/` (caught a foot-gun: I first deployed to the duplicate `/usr/local/www/pdhcips/pdhcips/gateway/...`; the live gunicorn at pid 1243 actually serves from the single-pdhcips path). HUP'd master 1243; workers respawned 8650→41655 and 15814→41656; `/api/v1/health` 200 after. Local edits were initially made to `pdhcips/gateway/app/templates/` and mirrored to the git-tracked `gateway/app/templates/` so the canonical repo paths see the change.

- 2026-06-02: gateway/app/api/clinic_routes.py — new endpoint `GET /api/v1/clinics/<guid>/patients` joining `PatientClinicAssignment` → `PatientIndex`, ordered by `(family_name, given_name)`, filtered on `PatientIndex.is_active`. Source of truth for "this organisation's patients" across PDHC (consumed by sim.pdhc Cohort Builder rework, Step A of the plandef-driven flow).
- 2026-06-02: gateway/tests/test_api_endpoints.py — new `TestClinicPatients` class, 5 tests: happy-path list (ordered), no cross-clinic leakage, patient-in-two-clinics appears in both, unknown clinic → 404, empty clinic → []. 174/174 tests green.
- 2026-06-02: gateway/app/templates/docs_api.html — added endpoint reference card under "Application — Clinics" with full response shape + dedupe + active-filter notes.
- 2026-06-02: gateway/app/templates/docs_manual.html — new "Clinic patient lists (cross-service)" section explaining IPS as source of truth for org→patients, plus how assignments are created (no public POST) and the active/inactive semantics.
- 2026-06-02: gateway/app/templates/docs_technical.html — bumped Clinics row in API surface table (4 → 5 endpoints), added "Patient ↔ clinic (organisation) relationship" sub-section under Data Model explaining many-to-many shape, clinic-as-organisation vocabulary, cross-service query path, and why FHIR `GET /Patient` deliberately has no clinic filter.
