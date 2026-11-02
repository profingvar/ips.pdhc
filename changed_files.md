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
- 2026-06-03: gateway/app/api/clinic_routes.py — new endpoint `POST /api/v1/clinics/<guid>/patients` for programmatic patient import. Accepts either a flat shape (family_name/given_name/gender/birth_date/identifier_*) or a full FHIR Patient resource under `fhir:`. Creates the PatientIndex via `create_resource("Patient", ...)` then INSERTs PatientClinicAssignment so the patient is queryable via the GET sibling. Used by sim.pdhc's Synthea importer (Shape C of the Synthea hookup, see sim.pdhc commit 5ae4822). Logs `clinic_patient_create` events; same `@require_auth` as siblings.
- 2026-06-03: gateway/tests/test_api_endpoints.py — new `TestCreateClinicPatient` class, 5 tests: create from flat fields lands in roster, create from full FHIR body lands in roster, missing required fields → 400, unknown clinic → 404, full FHIR with wrong resourceType → 400. Brings ips.pdhc suite to 179/179.

- 2026-06-09 (#198 IPS Renov 2 — PatientConsent schema + API + audit):
  - gateway/app/models/patient_consent.py (NEW): peer model to PatientBlock.
    Columns: guid pk, patient_guid (FK PatientIndex), grantee_caregiver_guid,
    contract_guid (nullable, references contract.pdhc), granted_at,
    granted_by_user_guid, granted_via enum('portal'|'in_person'|'paper'|'phone'|'other'),
    granted_note, expires_at, revoked_at, revoked_by_user_guid,
    revoked_reason, consented_concept_guids JSONB|NULL. `is_active()`
    returns True iff revoked_at is NULL AND (expires_at is NULL OR > now).
    `to_dict()` mirrors the block shape.
  - gateway/app/models/__init__.py: register PatientConsent.
  - gateway/app/api/consents_routes.py (NEW): three endpoints under
    /api/v1/patients/<guid>/consents:
      * POST                                       — grant
      * GET ?active=true|false                     — list
      * POST /<consent_guid>/revoke                — revoke
    Auth mirrors blocks_routes: SU admin OR staff with a PatientClinicAssignment
    to the patient. Duplicate active consent to the same grantee → 409. Concept-
    narrowed grants accept a list of concept guids; full-caregiver grants leave
    consented_concept_guids NULL. expires_at parsed via ISO-8601 (trailing Z
    accepted). Each route emits an AuditLog event: consent.granted /
    consent.revoked. Schema lands via the existing create_all bootstrap (ips
    does not maintain Alembic versions despite having the harness — every
    model addition since PatientBlock was added this way).
  - gateway/app/__init__.py: register consents_bp.
  - gateway/tests/test_consents_api.py (NEW, 19 tests):
      * Grant: admin happy + audit row; staff-with-relationship; unrelated
        staff 403; missing/invalid grantee 400; invalid granted_via 400;
        duplicate active 409; concept-narrowed; bad concept guids 400;
        expires_at parse; bad expires_at 400; patient 404.
      * List: admin sees all; unrelated staff 403; active filter excludes
        revoked rows; active=false includes them.
      * Revoke: admin happy + audit row; double-revoke 409; not-found 404.
      * Expiry: a past expires_at makes is_active() False; default active
        list filter hides it.
    Full ips suite 229/229 green (up from 179/179).

- 2026-06-09 (#202 IPS Renov 6 — background block expiry + cache-invalidation webhook):
  - gateway/app/models/patient_block.py: new `expires_at` column
    (nullable, mirrors PatientConsent shape). `is_active()` now
    short-circuits to False when `expires_at` has passed regardless
    of lift state. `to_dict()` surfaces the field.
  - gateway/app/services/block_expiry_service.py (NEW):
      * `expire_blocks()` flips rows where `expires_at < now AND
        lifted_at IS NULL` to `lifted_at=expires_at`,
        `lifted_reason='expired'`, `lift_kind=None`. Emits a
        `block.expired` AuditLog row + dispatches the webhook.
      * `re_impose_indispensable_lifts()` flips rows where
        `lift_kind='indispensable_care' AND lift_expires_at < now`
        back to fresh-active (clears the entire lift record).
        Emits `block.re_imposed`.
      * `sweep()` runs both passes; consumed by the CLI.
  - gateway/app/services/block_webhook.py (NEW): outbound HMAC-SHA256
    signed notifications. Header `X-PDHC-Signature: sha256=<hex>` +
    `X-PDHC-Event: <event_type>`. Body is sorted-keys canonical JSON
    carrying `event_type`, `block_guid`, `patient_guid`,
    `source_scope_{type,id}`, `is_active`, `occurred_at`. One shared
    IPS-level secret (`IPS_WEBHOOK_SECRET`) and a comma-separated
    target list (`IPS_WEBHOOK_TARGETS`). Best-effort: per-target
    failures count + log, never raise; `safe_dispatch()` wraps for
    callers who must not surface errors. Uses `httpx` (matches ips
    requirements.txt).
  - gateway/app/api/blocks_routes.py: `create_block` and `lift_block`
    now call `safe_dispatch('block.created'|'block.lifted', block)`
    after `db.session.commit()` so a webhook failure can't roll back
    the state change.
  - gateway/app/__init__.py: registers the `flask sweep-blocks` CLI.
    Operator cron snippet (hourly is fine for v1; ticket calls for
    minute-cadence in v2 if blocks routinely carry short
    expires_at):
        0 * * * * cd /usr/local/www/pdhcips/gateway \
                 && docker exec ips-app-1 flask sweep-blocks \
                 >> shared/logs/block_sweep.log 2>&1
  - gateway/app/config.py: new `IPS_WEBHOOK_SECRET` / `IPS_WEBHOOK_TARGETS`
    / `IPS_WEBHOOK_TIMEOUT` config knobs.
  - gateway/tests/test_block_expiry_and_webhook.py (NEW, 18 tests):
      * Signing (2): signature format + value; canonical body shape.
      * Dispatch (6): signs + posts each target; identical body and
        signature across targets; skips when secret missing; skips
        when target list empty; counts HTTP failures; rejects unknown
        event_type; safe_dispatch swallows exceptions.
      * Sweep — expire (4): past deadline -> flip + audit; future
        deadline untouched; already-lifted untouched; no expires_at
        untouched.
      * Sweep — re-impose (3): past lift_expires_at -> clear lift +
        audit; still-in-window untouched; consent lifts never re-imposed.
      * Sweep one-shot (1): runs both passes in one call.
      * Route end-to-end (2): create_block fires block.created;
        lift_block fires block.lifted.
    Full ips suite 247/247 green (up from 229/229).

- 2026-06-09 (#201 IPS Renov 5 — admin indispensable-care block lift):
  - gateway/app/api/admin_blocks_routes.py (NEW): new blueprint
    `admin_blocks_api` at `/api/v1/admin/blocks/<block_guid>/lift`.
    POST endpoint restricted to SU admin OR roles in
    `IPS_INDISPENSABLE_LIFT_ROLES` (default `physician,admin`).
    Body: `reason` (required, non-empty), `concept_guids` (required,
    non-empty, all valid UUIDs), `expires_in` (seconds, default 24h),
    optional `from_date` / `until_date` (ISO-8601 narrowing).
    On success: sets `lift_kind='indispensable_care'`, `lifted_by_user_guid`,
    `lifted_reason`, `lift_concept_guids`, `lift_expires_at`. Audit row
    has `event_type='block.lifted'`, `detail.mechanism='indispensable_care'`,
    `detail.actor_user_guid`, `detail.reason` verbatim, `detail.admin_route=True`.
    Webhook (#202) fires `block.lifted` post-commit.
    Returns 200 (lifted), 400 (missing/invalid field), 403 (role gate),
    404 (block not found / bad guid), 409 (already lifted).
  - gateway/app/__init__.py: register `admin_blocks_bp`.
  - gateway/tests/test_admin_blocks_lift.py (NEW, 17 tests):
      * Role gate (3): SU admin lifts, physician role lifts, operator 403.
      * Validation (9): missing/whitespace reason 400; missing concepts 400;
        bad concept-guid shape 400; negative expires_in 400; bad ISO date 400;
        invalid block_guid format 404; unknown block 404; double-lift 409.
      * State + audit (3): persists all lift fields with 24h default;
        custom expires_in honoured; audit row carries mechanism + actor +
        reason verbatim + admin_route=True.
      * Auto-re-impose integration (1): after lift_expires_at passes,
        the #202 sweep flips the block back to fresh-active.
      * Webhook (1): block.lifted fires post-commit.
    Full ips suite 264/264 green (up from 247/247).

- 2026-06-09 (#204 IPS Renov 8 — cross-caregiver block check):
  - gateway/app/api/blocks_routes.py: new endpoint
    `GET /api/v1/patients/<guid>/blocks/check?source_clinic_id=&source_caregiver_id=`
    that answers "is data from source X readable for patient P?" in
    one round-trip, consulting BOTH clinic-level AND caregiver-level
    blocks. The consumer resolves `source_caregiver_id` from the SSO
    Phase 1 (#188) `organization_caregivers` blob; passing it lets
    one query cover the entire caregiver subtree without enumerating
    its clinics. Returns `{is_blocked, blocking_scopes: [{scope_type,
    scope_id, block_guid, lift_kind, lift_concept_guids,
    lift_from_date, lift_until_date, lift_expires_at}]}`. Tightened
    matching: clinic-scope rows match clinic candidate; caregiver-scope
    rows match caregiver candidate; no cross-bleed if guids collide.
    Auth: no PatientClinicAssignment required — this is the predicate
    consulted on cross-caregiver reads where the relationship is the
    very thing being protected.
  - gateway/tests/test_blocks_check_cross_caregiver.py (NEW, 13 tests):
      * Round-trip (1): create + list + lift a caregiver-scope block;
        AuditLog has block.created and block.lifted rows.
      * Shape (5): no blocks → not blocked; missing/bad clinic id
        → 400; bad caregiver id → 400; unknown patient → 404.
      * Clinic-level (1): clinic-scope block blocks only that clinic.
      * Caregiver-level (3): caregiver-scope block hides every
        clinic under that caregiver; doesn't bleed to other caregivers'
        clinics; consumer that omits source_caregiver_id is
        backwards-compatible (sees clinic-level only).
      * Lift propagation (1): lifting a caregiver-level block clears
        the verdict for every clinic in the subtree in one action.
      * Combined blocks (1): both scopes blocked → both surface;
        consumer can pick whichever lift it consults.
      * Lift surfaces in check (1): an active indispensable_care
        lift surfaces with its concept_guids + date narrowing + expiry
        so the consumer can apply the mechanical filter downstream.
    Full ips suite 277/277 (was 264/264).

- 2026-06-09 (#208 Spärr ops — historical-data migration confirmation):
  - docs/technical.md (NEW): negative-confirmation note in the
    "Spärr — historical data migration confirmation" section. Swept
    `ips_db`, `dashboard_pdhc_db`, `gateway_pdhc_db`,
    `request_pdhc_db` schemas for any column name matching
    share/hidden/opt/nopat/exclud/spar/no_disclose — 0 hits across
    all 4 schemas. Swept IPS `fhir_resources.resource_json` for
    Patient rows carrying `NOPAT`/`confidentiality`/`restricted` or
    any populated `meta.tag[]` — 0 hits. Swept dashboard
    `observation_cache.raw` for the same security-label strings — 0
    hits. Documented the sweep SQL for reproducibility. No one-off
    PatientBlock migration owed from legacy data; conclusion records
    that future audits don't need to re-ask the question.

## 2026-07-02 — rollup #349 commit-1 (7 surgical child tickets)

  - #382 §1.1 gateway/Dockerfile: gunicorn --bind changed from
    `0.0.0.0:9040` to `127.0.0.1:9040`. Layering-violation fix per
    platform CLAUDE.md §3.
  - #383 §1.2 gateway/Dockerfile: added
    `--access-logfile -` + `--access-logformat` so HTTP requests are
    audit-visible in `docker logs`. Matches request.pdhc #370.
  - #384 §1.3 gateway/docker-compose.yml: replaced
    `${POSTGRES_PASSWORD:-dev}` (silent fallback) with
    `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}` on
    both the `db` env and the `app` DATABASE_URL. Fail-fast per
    platform CLAUDE.md §9.
  - #385 §1.4 gateway/Dockerfile: added HEALTHCHECK block (curl
    /api/v1/health, 10s interval, 3s timeout, 3 retries) + curl to
    the apt install list (needed for the healthcheck itself).
  - #386 §2.1 gateway/app/api/health.py: /api/v1/health now returns
    HTTP 503 when db_status != connected. Was always 200 with
    `status:degraded` — the CLAUDE.md §10 false-green pattern.
    Regression guard added in gateway/tests/test_health.py.
  - #387 §3.1 gateway/app/fhir/fhir_routes.py: CapabilityStatement
    .date now derives from `os.path.getmtime(__file__)`, stable
    across workers and requests, advancing only on real image
    rebuild. Matches request.pdhc #367 + memory
    `infra_gunicorn_worker_fork_freezes_datetime`.
  - #388 §3.3 gateway/app/fhir/fhir_routes.py: CapabilityStatement
    now carries id / url / version / name / title / publisher /
    description + `implementation` block (satisfies cpb-14 for
    kind=instance).
  - gateway/tests/test_health.py: added
    `test_health_returns_503_when_db_disconnected` — regression
    guard for the false-green fix. 4/4 pass, full 358/358 suite
    still green.

## 2026-07-02 — rollup #349 commit-2 (truth test + pytest CI + conformance CI)

  - #391 gateway/tests/test_capability_truth.py (NEW): bidirectional
    walker between /fhir/metadata CapabilityStatement and
    app.url_map. Direction (a) checks that every advertised
    (resource_type, interaction) resolves to a real Flask route
    (accepts either the hardcoded /fhir/Patient shape or the generic
    /fhir/{*} clinical-CRUD shape). Direction (b) checks that every
    type in SUPPORTED_RESOURCE_TYPES is advertised in the CS. Also
    verifies the $ips operation URL resolves. 4/4 pass.
  - #390 gateway/tests/conformance_corpus_emit.py (NEW): boots a
    self-contained testing-config Flask app (sqlite in-memory), emits
    the CapabilityStatement into gateway/tests/fhir_corpus/. Rule
    15 A scope — clinical resource shape polish deferred to a design
    ticket.
  - #390 gateway/Makefile (NEW): local dev + rollup #349 conformance
    targets. `make test` runs the pytest suite. `make corpus` and
    `make conformance` mirror the termbank / request.pdhc pattern.
    VALIDATOR_JAR defaults to ~/.local/share/fhir/validator_cli.jar.
  - #390 gateway/tests/fhir_corpus/capability_statement.json (NEW,
    committed): reference corpus. Deterministic — regenerated by
    `make corpus` on every CI run and diff-checked against what the
    current code emits.
  - #389 .github/workflows/test.yml (NEW): first CI for ips.pdhc.
    Python 3.12 matches Dockerfile base. Paths filter targets
    gateway/** + this workflow. Runs `pytest tests` on push + PR.
    Config comes from config.TestingConfig (in-memory sqlite,
    AUTH_DISABLED=True).
  - #390 .github/workflows/conformance.yml (NEW): Java 17 + Python
    3.12 + cached validator_cli.jar 6.9.10 against tx.fhir.org/r5.
    Paths filter targets gateway/app/fhir/**, fhir_service.py,
    capability_statement.py, the corpus emitter, requirements.txt,
    Makefile, and this workflow. 15-min timeout (loads
    hl7.fhir.uv.ips.r4 package via the $ips OperationDefinition
    reference). Uploads corpus artifact on failure.

  Local `make conformance` result: 0 errors, 0 warnings, 1 note.
  Full pytest: 363/363 pass (+5 vs commit-1 baseline: 4 truth test +
  1 health 503 guard).

## 2026-07-03 — rollup #349 close-out (#392 delete dead API_KEY_SECRET)

  - #392 gateway/app/config.py + gateway/.env.example +
    gateway/server_configs/deploy.md: dropped the `API_KEY_SECRET`
    env var / config attribute / .env.example line / deploy.md
    row. It was reserved for Fernet-encrypting push-destination
    credentials (readme.md §5.d, ticket #6) but never wired to any
    code path (verified via `grep -rn API_KEY_SECRET` — only its own
    declaration, no readers). Kept a short comment in config.py
    where the line was removed, pointing at #392 and stating the
    "don't design for hypothetical future requirements" rationale.
    If push-cred encryption ever ships, add the key handling fresh.
    Tests: 363/363 unchanged.

## 2026-07-03 — Access-model reform D1 (#404): patient opt-out flags
- gateway/app/models/patient_index.py — added ehds_opt_out (Bool default
  False), quality_registry_opt_out (Bool default False),
  consented_research_projects (JSONB list) to PatientIndex; updated
  to_dict(); added primary_care_unit_guids() derived from existing
  PatientClinicAssignment rows. Reconciliation documented in-file: the
  other two v3-spec consents already exist richer — allow_sharing_in_care
  → PatientConsent (#198, per-caregiver), primary_care_unit_guids →
  PatientClinicAssignment. Only the 2 booleans + research list are new.
- gateway/migrations/add_reform_patient_flags.sql — NEW. Idempotent ALTER
  (IF NOT EXISTS) for prod, since ips uses db.create_all() which never
  alters existing tables. Operator runs it after deploy.
- gateway/tests/test_models.py — added 3 D1 tests (defaults, set/round-trip,
  primary_care_unit_guids from assignments). 17/17 pass.

## 2026-07-07 — #422 analysis-enforcement foundation (consent policy in ips)
- gateway/app/services/consent_policy.py — NEW canonical policy
  evaluate_patient(flags, purpose, reader_research_project_guids): the 3 rules
  (EHDS opt-out blocks secondary-use; research needs project-consent
  intersection; quality_registry_opt_out blocks qreg). ips owns the flags so it
  owns the policy — one legal source of truth.
- gateway/app/api/patient_routes.py — NEW POST /api/v1/patients/analysis-filter:
  analysis services POST {patient_guids, purpose, research_project_guids} and
  get back {allowed, excluded:[{patient_guid, reason}]}.
- gateway/tests/test_consent_policy.py — NEW, 8 tests (policy + endpoint).
- Suite 374/374.
- ips.pdhc/docs/technical.md (Port Allocation section)
- gateway/app/api/consents_routes.py — NEW endpoint GET /api/v1/patients/<pid>/consents/check?grantee_caregiver_guid=<cg> (relationship-free cross-service consent predicate; #558, mirrors blocks_routes.check_block)
- gateway/tests/test_consents_api.py — +TestCheckConsent (6 tests: relationship-free, grantee filter, active-only, 400/404). Suite 402/402.
- gateway/app/api/patient_routes.py
- gateway/tests/test_consent_policy.py

## 2026-10-07 — euIPS Phase A (#789 personnummer, #790 move the generator)
| 2026-10-07 | gateway/app/services/personnummer.py | NEW — build / normalise / is_valid / describe_invalid + the OID, one definition for three callers |
| 2026-10-07 | gateway/app/admin.py | generator uses pnr.build (was a doubled century + random check digit); admin create normalises and warns; patients view syncs SSO orgs and passes `orgs` |
| 2026-10-07 | gateway/app/api/clinic_routes.py | POST /clinics/<guid>/patients normalises + validates only on the Swedish OID; `current_app` imported (it was used and missing) |
| 2026-10-07 | gateway/app/templates/dashboard.html | Generate Mock Patients block removed |
| 2026-10-07 | gateway/app/templates/patients.html | generator block added beside Create Patient; empty-state no longer points at the dashboard |
| 2026-10-07 | gateway/app/__init__.py | NEW `flask check-personnummer` — read-only report |
| 2026-10-07 | gateway/tests/test_personnummer_789.py | NEW — 27 tests |
| 2026-10-07 | gateway/tests/test_mock_generator_789_790.py | NEW — 12 tests, 9 fail without the fix |

## 2026-10-07 — euIPS #791 (the DB decision)
| 2026-10-07 | gateway/app/services/euips_sections.py | NEW — the 17-section catalogue, absent-code helpers, computed status, is_conformant |
| 2026-10-07 | gateway/app/models/patient_index.py | + `generation_batch_guid` (nullable UUID), surfaced additively in to_dict |
| 2026-10-07 | gateway/migrations/add_generation_batch_guid.sql | NEW — idempotent ALTER; UUID not VARCHAR |
| 2026-10-07 | gateway/app/api/patient_routes.py | + GET /patients/<guid>/euips-sections (computed); `_is_uuid` hoisted to module scope |
| 2026-10-07 | gateway/tests/test_euips_sections_791.py | NEW — 20 tests |
| 2026-10-07 | plans/euips_reform.md | the #791 decision record |

## 2026-10-07 — euIPS #793 (the three REQUIRED sections)
| 2026-10-07 | gateway/app/services/euips_required.py | NEW — the three required sections, content or explicit absence, with narrative |
| 2026-10-07 | gateway/app/services/euips_sections.py | `is_absent_assertion` now covers `medication` (what this codebase writes) + CodeableReference; `_CODE_BEARING_FIELDS` |
| 2026-10-07 | gateway/app/admin.py | required sections emitted in BOTH modes; removed from `_mock_patient_resources`; dead `_CONDITIONS`/`_MEDICATIONS`/`_ALLERGIES` deleted; flash reports conformance |
| 2026-10-07 | gateway/tests/test_required_sections_793.py | NEW — 13 tests, 6 fail without the fix |

## 2026-10-07 — euIPS #794 (the four RECOMMENDED sections)
| 2026-10-07 | gateway/app/services/euips_recommended.py | NEW — immunisations (age-derived dates), procedures, Device + DeviceUseStatement, diagnostic results WITH linked Observations |
| 2026-10-07 | gateway/app/admin.py | recommended sections wired in; immunisations/procedures/diagnostic reports removed from `_mock_patient_resources`; dead `_IMMUNIZATIONS`/`_PROCEDURES`/`_DIAGNOSTIC_REPORTS` deleted |
| 2026-10-07 | gateway/tests/test_recommended_sections_794.py | NEW — 14 tests, 6 fail without the fix |

## 2026-10-07 — euIPS #795 (the seven OPTIONAL sections) + a #791 fix it forced
| 2026-10-07 | gateway/app/services/euips_optional.py | NEW — vital signs, past illnesses, pregnancy (sex/age-gated), social history, functional status, CarePlan, FHIR Consent |
| 2026-10-07 | gateway/app/services/euips_sections.py | per-section `discriminator` + `section_matches` + `absent_section_key`; `status_for_resources` rewritten to discriminate shared resource types |
| 2026-10-07 | gateway/app/admin.py | optional sections wired; `_mock_patient_resources` and `_OBSERVATIONS` deleted — every section now has a dedicated module |
| 2026-10-07 | gateway/tests/test_required_sections_793.py | the problem-list test narrowed to the real invariant |
| 2026-10-07 | gateway/tests/test_optional_sections_795.py | NEW — 18 tests, 9 fail without the fix |

## 2026-10-07 — euIPS #796 (the three EU additions) + two more discriminator subtractions
| 2026-10-07 | gateway/app/services/euips_eu_additions.py | NEW — Flag alerts with simulated provenance, travel history as a period, patient-provided via performer==subject |
| 2026-10-07 | gateway/app/services/euips_sections.py | `TRAVEL_CODES` settled provisionally (SNOMED 420008001); `obs_social_history` and `obs_survey` made SUBTRACTIVE |
| 2026-10-07 | gateway/app/admin.py | EU additions wired into the generator |
| 2026-10-07 | gateway/tests/test_eu_additions_796.py | NEW — 14 tests, 7 fail without the fix |
| 2026-10-07 | gateway/tests/test_optional_sections_795.py | the travel placeholder test narrowed to the surviving invariant |

## 2026-10-07 — euIPS #797 (100 per provider, as an undoable batch)
| 2026-10-07 | gateway/app/services/euips_batch.py | NEW — list_batches / conformant_count / batch_preview / purge_batch with EXPLICIT dependent deletes |
| 2026-10-07 | gateway/app/admin.py | one batch guid per run, stamped on each patient; `POST /admin/mock-data/purge`; batch list passed to the template; flash reports the batch guid and resource count |
| 2026-10-07 | gateway/app/templates/patients.html | generation-batch table with per-batch counts, euIPS conformance and a Purge button |
| 2026-10-07 | gateway/tests/test_batches_797.py | NEW — 17 tests, 11 fail without the fix |

## 2026-10-07 — euIPS #798 (pin the consumers)
| 2026-10-07 | gateway/tests/test_consumer_contract_798.py | NEW — 13 tests pinning the verified consumer contract |
| 2026-10-07 | gateway/scripts/contract_check.py | NEW — runs against a LIVE ips; route registration + response shapes |

## 2026-10-07 — euIPS #799 (the completeness report)
| 2026-10-07 | gateway/app/services/euips_report.py | NEW — per-obligation coverage, conformance, capped failure list, the disclaimer |
| 2026-10-07 | gateway/app/__init__.py | `flask euips-report` and `euips-report-batch` |
| 2026-10-07 | gateway/scripts/contract_check.py | MOVED here from the repo-root scripts/ so `COPY . .` ships it into the image |
| 2026-10-07 | gateway/tests/test_euips_report_799.py | NEW — 15 tests |
- 2026-10-14 gateway/app/api/patient_routes.py — #825: POST /api/v1/patients/search (demographic predicate -> patient guids, Rule 24 scoped)
- 2026-10-14 gateway/tests/test_patient_search.py (NEW)

## 2026-10-15 — #708 sibling smoke, and the defect it found on its first run
- gateway/deploy/smoke_siblings.py                 (NEW: the sibling smoke; 10 checks, read-only)
- gateway/app/services/care_hierarchy_sync.py      (read the sso base url key ips actually SETS)
- gateway/tests/test_care_hierarchy_sso_url.py     (NEW: pins the resolution order)
- app/api/care_access_routes.py — POST /api/v1/patients/care-access-filter: the BULK care twin of analysis-filter

## EPS + patient state assessment (2026-10-30)

New:

- `/Users/martiningvar/T7_sidewinder/ips.pdhc/plans/eps_state_reform.md` —
  assessment of (1) renaming IPS→EPS, (2) EPS conformance against
  `plans/euips_reform.md`'s existing work, (3) a bitemporal patient-state store
  with next-of-kin privileges. Read-only measurement; no code changed.

- `/Users/martiningvar/T7_sidewinder/ips.pdhc/plans/eps_state_plan.md` — the
  numbered build plan derived from that assessment: three decisions (E1–E3),
  then phases 2, 3 and 1 with a measurable "done when" per step
- `/Users/martiningvar/T7_sidewinder/ips.pdhc/plans/eps_state_plan.docx` —
  the same plan typeset for paper
- `/Users/martiningvar/T7_sidewinder/ips.pdhc/make_eps_plan_docx.py` — pandoc
  + python-docx converter for the above, after alert.pdhc/make_plan_docx.py

Also published, outside this repo:

- Claude Docs artifact `https://claude.ai/artifact/T3x8WRyY5Gc6xywj1cSnjq` —
  the plan as a shareable page, with a drawn dependency/gate diagram. Private
  until shared from the page's Share menu.

Edited:

- `/Users/martiningvar/T7_sidewinder/ips.pdhc/changed_files.md` — this entry

## 2026-10-30 — #858: the container bind, and the docs that still said bare-metal

Edited:

- `/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/Dockerfile` — CMD
  `--bind 127.0.0.1:9040` → `--bind 0.0.0.0:9040`, and the #349 §1.1 comment
  above it replaced with why, so it is not reinstated. The old comment's
  concern was real but sat in the wrong layer: inside a container the loopback
  interface is the container's own, so binding it removes reachability instead
  of narrowing it. `docker-compose.yml:29` (`127.0.0.1:9040:9040`) is the
  control and is deliberately untouched; so is the HEALTHCHECK, which is
  correct to probe from inside.
- `/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/templates/docs_technical.html`
  — the runtime-topology table said the app was bare-metal Python started by
  `start.sh`, "**not** in Docker". It runs as `ips-app-1` (compose project
  `ips`, service `app`) and no gunicorn runs on the host for 9040. Row
  rewritten; the "Why split" note replaced with the containerised reality plus
  the bind explanation and its measurement.
- `/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/templates/docs_manual.html`
  — four fixes. Backup section no longer claims the app is bare-metal. Restart
  section rewritten to `docker-compose up -d --no-deps app|db`, with the
  service-vs-container-name trap named (`up -d --no-deps ips-app-1` fails with
  `no such service`). **Two of its instructions were not merely stale but
  broken**: it pointed at `/usr/local/www/pdhcips/pdhcips/gateway`, a
  duplicated path that is not the deployed working directory, and told the
  operator to read `~/.gunicorn/ips.pid`, which does not exist. Env-var warning
  widened to both containers. Log commands moved off the deleted host log files.
- `/Users/martiningvar/T7_sidewinder/CLAUDE.md` — §3's bind rule gained a
  containerised clause (it previously made any containerised service
  unreachable if followed literally) and §14's confirm-first entry now says
  "on the host" and points at it.

Verified, not asserted — the image was built both ways locally and run against
a throwaway Postgres:

```
--bind 127.0.0.1   container Up (healthy)   host via mapping: 000
--bind 0.0.0.0     container Up             host via mapping: 200
```

The control is what makes the second row evidence. Jinja parse check on all
three templates passed (run inside `ips-app:latest`, since jinja2 is not in the
host interpreter). Test containers, network and images removed; local container
count unchanged at 19.

NOT changed: production. `ips-app-1` has run `--bind 0.0.0.0:9040` all along —
the repo was the divergence, and the repo is what a `--build` would have
deployed. No redeploy was performed.

---

## 2026-11-02 — #881 (EPS B1): the two LOINC codes the EPS specification supplies

- `gateway/app/services/euips_sections.py`
- `gateway/tests/test_eps_section_codes_881.py` (new)

    section            was    now
    alerts             None   104605-1
    travel_history     None   10182-4
    patient_provided   None   None — DELIBERATELY, see below

**The win existed only because nothing was guessed.** `CODES_VERIFIED = False`
and a `None` LOINC were deliberate; the note on `alerts` read *"LOINC code not
established for this EU addition — left None rather than guessed."* When the
real values arrived there was nothing to unpick. The alternative is on record
elsewhere in this project as 51 and 58 corrections (#810/#816).

Both notes now say **where the value came from** — the EPS specification,
dated, and that it is a CI-build of a STU 1 Ballot — rather than that it is
missing. A code with no provenance is indistinguishable from a guess, which is
the state this change exists to leave behind, so a test asserts the provenance
survives a future edit.

`patient_provided` stays `None` and its note now records that as the #880
decision rather than a gap: EPS does not profile it at all, so it is a DOMESTIC
section. The note ends *"Do not fill this in to make the catalogue look
complete."*

`travel_history`'s note also warns against the layer confusion: `10182-4` is
the Composition SECTION code, while `TRAVEL_CODES` holds the SNOMED code on the
Observation itself.

`CODES_VERIFIED` is untouched. Filling a code from a document is not verifying
it against the published IG — that is #885.

**758 passed** (750 before). Controls proven by deliberate breakage:

| breakage | red |
|---|---|
| revert both codes to None | 3 |
| fill `patient_provided` too (the over-eager change) | 2 |
| flip `CODES_VERIFIED` to True | 6, across four test files |

The third shows the flag was already guarded in two pre-existing files; the new
test joins them rather than duplicating them.

---

## 2026-11-02 — #898 (EPS B8): DeviceUseStatement -> DeviceUsage, write new / read both

- `gateway/app/services/euips_sections.py`
- `gateway/app/services/euips_recommended.py`
- `gateway/tests/test_eps_device_usage_898.py` (new)
- `gateway/tests/test_recommended_sections_794.py` (two references rewritten)

R5 renamed the resource; this repo emitted the R4 spelling while
`fhir_routes.py:280` declares `fhirVersion: "5.0.0"`. The R5 claim was false in
that one respect — and it matters more since #877 chose to EXPORT R5 rather
than render R4, because the export's correctness now rests entirely on the
stored shapes being R5.

**Write the new name, read both.** `fhir_resources.resource_type` is a plain
`String(64)`, so rows keep whatever was written. The production count of old
rows could NOT be measured (the read was not permitted), so nothing was
migrated blind:

    LEGACY_RESOURCE_TYPES = {"DeviceUseStatement": "DeviceUsage"}

normalised in `section_matches()` only, with the removal condition written next
to it: once the count is 0 in every deployment, the entry and the
normalisation go together.

**The alias is deliberately NOT in `Section.resource_types`.** That tuple is
serialised into the `/patients/<guid>/euips-status` response, so it tells a
producer what to WRITE. An alias published there is an invitation to keep
using it. A test asserts the legacy name appears in no section's tuple.

**Two existing tests were rewritten, not deleted**, and the second one is the
interesting half:

  - `test_a_device_has_a_use_statement_pointing_at_it` -> `..._a_usage_...`.
    The property is unchanged; only the type name moved.
  - the narrative loop at line ~221 iterated `"DeviceUseStatement"`. Left
    alone it would have **kept passing while checking nothing**: `_rows` on a
    type nothing writes returns `[]`, and an empty inner loop asserts nothing.
    That is the silent form of the same defect, and a comment now says so.

The stale catalogue note is gone. It claimed *"THE MISSING ONE. No Device
resource type exists in fhir_resources at all"*, which had been wrong since
2026-10-07 when #794 added the builder — and was quoted into
`plans/eps_state_reform.md` §2.5 as fact. The module docstring's *"What was
wrong before"* entry is left alone: it is past tense and labelled as history.

**772 passed** (758 before). Controls proven by deliberate breakage:

| breakage | red |
|---|---|
| builder emits the R4 name again | 3 |
| drop the alias normalisation from the matcher | 2 |
| publish the alias in `resource_types` | 2 |

**Still unmeasured, and tracked in the code rather than as a caveat:** how many
production rows carry the old spelling. The accept-both read path makes the
answer non-blocking, but the removal condition needs it.

---

## 2026-11-02 — #883 (EPS B3): Device and DeviceUsage made visible to the API

- `gateway/app/services/fhir_service.py` (`SUPPORTED_RESOURCE_TYPES`)
- `gateway/app/services/euips_recommended.py` (three IG questions recorded)
- `gateway/tests/test_eps_device_api_883.py` (new)

EPS makes section 46264-8 **1..1**, so these must be writable and advertised.
**The gap was visibility, not existence** — and the correction changed what the
fix was. They were already generated (#794) and already storable (`resource_type`
is a free `String(64)`); they were missing only from
`SUPPORTED_RESOURCE_TYPES`, which gates the generic `/fhir/<type>` handler and
feeds `_default_capability_statement`. Adding them made the CapabilityStatement
follow with no further edit, because the generator loops that list and
`test_capability_truth.py` asserts the two agree in both directions.

**A risk checked and found already handled.** I expected the create route to
read patient linkage from `subject` only, which would have stored every Device
with `patient_guid` NULL — silently dropping it out of patient-scoped reads and
Rule 24 scope. It already has a `patient` fallback, with a comment saying why.
So nothing was built for it; a test pins that it keeps working for the newly
admitted types, and a third test pins that a body with NEITHER field is stored
unlinked, so the linkage is known to come from the body rather than from the
type being admitted.

**Accept-both does not extend to the API.** `POST /fhir/DeviceUseStatement` is
refused `not-supported`. Reading stored rows under the old spelling is #898's
concession; admitting new ones would mean the alias never becomes removable.

The absent-code half needed no work: `_BUILDERS` already carries
`("devices", … "no known devices")` and `test_recommended_sections_794.py:184`
already asserts every recommended section exhibits PRESENT,
EXPLICITLY_ABSENT and MISSING. Not duplicated.

**Three element names recorded as UNVERIFIED and deliberately not changed**
(now in the `_devices` docstring, for #885): `Device.patient` and
`DeviceUsage.subject` look swapped relative to R5, and the absent assertion
writes `Device.code` where R5 appears to use `type`. All three are inert today —
the create route reads both reference fields and the matcher keys on type — and
become real the moment an external validator sees the export. Deciding them
from memory is the guessing this module refuses to do.

**781 passed** (772 before). Controls: removing the two types -> 7 red;
admitting the legacy spelling -> 2 red.

---

## 2026-11-02 — #891 (EPS C4): an assignment could begin but never end

- `gateway/app/models/patient_index.py`
- `gateway/app/api/clinic_routes.py`
- `gateway/migrations/add_assignment_ended_at.sql` (new)
- `gateway/tests/test_eps_assignment_ended_at_891.py` (new)

**Two things had to change, not one.** The column alone would have made
"ended" a TERMINAL state per pair: `UniqueConstraint(patient_guid,
clinic_guid)` meant a closed row still occupied the pair, so a patient
returning to a clinic they had left could not be re-assigned. Replaced with a
PARTIAL unique index over open assignments — at most one active assignment per
pair, any number of closed ones. For every row that exists today (all
`ended_at IS NULL`) the rule is identical to the old constraint, so nothing
stored is affected.

`ended_at` is NOT a reuse of `expires_at`, which exists on four other models.
Those are EXPIRIES — a planned future end set at creation. This is an end that
HAPPENED. An expiry in the future means "still valid"; a non-NULL `ended_at`
always means "over". A test pins that `expires_at` is absent from this model.

**Ten read sites, and THREE are authorisation.** `blocks_routes` (spärr),
`consents_routes` and `care_access_routes` all grant on "staff with an
assignment to the patient". Flipping those to "an ACTIVE assignment" is a
TIGHTENING — staff at a clinic the patient left would lose access — which is
probably right and is still a security change that must not ride along with a
column addition. So:

  - one canonical rule, `PatientClinicAssignment.active_only(query)`, for the
    same reason `care_access_policy` is the single source of the zone rule
  - the ROSTER opts in (unambiguous: sim.pdhc builds cohorts from it, and a
    stale assignment puts a patient in a cohort they left)
  - the other nine are recorded in `CONSUMERS_OF_ASSIGNMENT` with the question
    each poses, and two tests assert the three auth sites are still HELD

`ips_generator`'s managing-organisation read is marked PROBABLY HISTORICAL: a
document generated then should carry the clinic current THEN, which is
bitemporal and belongs with #895.

**The migration was proven against real Postgres** in a throwaway container,
not merely written:

| | result |
|---|---|
| the DO block finds the auto-generated constraint name | dropped `patient_clinic_assignments_patient_guid_clinic_guid_key` |
| partial index created with the right predicate | `WHERE (ended_at IS NULL)` |
| existing row survives | `ended_at` NULL |
| re-run | clean no-op, *"already migrated"* |
| closed row + new open row, same pair | **accepted** |
| two OPEN rows, same pair | **refused** |

The name is looked up rather than hardcoded, because hardcoding it would
silently do nothing on a database named differently — and "silently did
nothing" is indistinguishable from success in a migration.

`sqlite_where` is given alongside `postgresql_where`: with only the latter,
SQLite (the test database) builds a FULL unique index, so the behaviour under
test would not have been the behaviour in production.

**792 passed** (781 before). Controls: roster ignores `ended_at` -> 1 red;
back to a full unique index -> 2 red.

**NOT deployed.** `add_assignment_ended_at.sql` has to be run on `ips-db-1`.

---

## 2026-11-02 — #899(b): three authorisation paths now require an ACTIVE assignment

- `gateway/app/api/blocks_routes.py` (spärr)
- `gateway/app/api/consents_routes.py`
- `gateway/app/api/care_access_routes.py`
- `gateway/app/models/patient_index.py` (`CONSUMERS_OF_ASSIGNMENT`)
- `gateway/tests/test_eps_assignment_auth_899.py` (new)
- `gateway/tests/test_eps_assignment_ended_at_891.py` (the two HELD tests rewritten)

All three answered *"does this staff member have a `PatientClinicAssignment` to
this patient?"* without asking whether it was still active. After #891 gave
assignments an end date, that meant staff at a clinic the patient had LEFT
would keep spärr, consent and care access.

**Done now because now it is free.** `ended_at` is NULL on all 296 production
rows and nothing can set it (#900). So "has an assignment" and "has an ACTIVE
assignment" return the same set, and the tightening changed no real answer on
the day it shipped. The empirical form: the suite went 792 -> 790 passing plus
exactly the two #891 tests that asserted these paths were untouched. **No other
test outcome moved.** Done after the first assignment ends, the identical edit
would be a behaviour change on a security path with real subjects.

Narrowed through `active_only()` at each site rather than an inline
`ended_at IS NULL`, so ten joins cannot drift into ten definitions of
"assigned".

`care_access_routes._assigned_clinic` returns None for an ended assignment,
which the caller treats as a DENIAL — the same #807-shaped case as a patient
with no care relationship at all, and the correct direction.

**The two #891 tests were rewritten, not deleted.** They asserted these paths
were HELD, which was true while #891 was the latest word; they are what made
this flip impossible to do silently, which was their purpose. Four tests now
pin the inventory instead: every site carries a decision, the count is 10,
nothing is HELD any more, and the two remaining OPEN QUESTIONs are named.

**802 passed** (792 before). Controls run PER SITE, because one narrowing
passing is not three:

| breakage | result |
|---|---|
| `blocks_routes` stops honouring `ended_at` | 1 red, the spärr test |
| `consents_routes` | 1 red, the consents test |
| `care_access_routes` | 1 red, the care-access test |

The third control had to be redone by hand. The first attempt mangled the file
with a regex de-indent, so pytest reported 8 ERRORs rather than one FAILURE —
a control that dies on an ImportError never ran the test, and would have been
scored as success by anyone reading only the exit code. The redo restores the
OLD LOGIC inside the NEW STRUCTURE and checks the module imports before
asserting anything.

**#900 carries part (a)**: the write path. Until it exists, all of this guards
a state that never occurs.

---

## 2026-11-02 — #882 (EPS B2): two free-text sections EPS declares and we do not carry

- `gateway/app/services/euips_sections.py` (`EPS_TEXT_SECTIONS`)
- `gateway/app/api/patient_routes.py` (the euips-sections response)
- `gateway/app/services/euips_report.py` (the dict and the rendered text)
- `gateway/tests/test_eps_text_sections_882.py` (new)

    81338-6   Patient Story / Patientens berättelse
    11329-0   Patient History / Sjukdomshistoria   (EPS-unique)

**They are deliberately NOT in `SECTIONS`, and that is the whole design.**
That tuple drives the resource-derived report: `status_for_resources` answers
PRESENT / EXPLICITLY_ABSENT / MISSING from the rows a patient has. Neither
answer is true of a section no resource backs.

  - MISSING reads as *"this patient lacks it"*, when the truth is *"this
    service does not carry this section at all"*. Every patient would carry two
    permanent MISSING rows — the coverage-report form of the always-partly-red
    monitor.
  - A fourth status would need four consumers updated and **one of them breaks
    silently**: `euips_report` spots a patient with nothing at all via
    `all(v == MISSING for v in st.values())`, and a status that is never MISSING
    makes that test permanently false. The other three are a `KeyError` in the
    matrix init, a dropped row in the endpoint's per-tier summary, and the
    tier-title map.

So they are declared separately and surfaced as **DECLARED and NOT CARRIED**,
which is strictly more informative than a status, on both the
`/euips-sections` response and the rendered report. The report wording says
"not per-patient" so a reader cannot count it as a patient gap.

**The ticket's estimate was "catalogue entries plus narrative generation". The
second half has no home yet** — measured, not assumed: the euIPS path assembles
no Composition. `euips_header.composition_header()` builds the header only
(*"the guideline's header is not a section"*), and the `Composition` with
`"section"` in `ips_generator.py` belongs to the older IPS-card path. Narrative
has nowhere to live until #896 (EPS B7) builds the export document, and a
half-generator before then would produce text no surface reads.

Both notes carry the #880 decision they depend on, because that is what stops a
later reader folding these into an existing section:

  - Patient Story is NOT `patient_provided`. The latter is information the
    patient ASSERTED, distinguished by source/performer, and #880 keeps it
    domestic.
  - Patient History is the only international home for resolved conditions
    once 11348-0 is unprofiled, and #880 decided AGAINST moving them —
    mapping coded resolved conditions into a free-text section destroys the
    coding, and `problems` / `past_illnesses` are told apart ONLY by
    `clinicalStatus`, so a merge would also put resolved illnesses in the
    ACTIVE problem list.

**813 passed** (802 before). Controls:

| breakage | red |
|---|---|
| drop the declaration | 6 |
| put them in `SECTIONS` — the design this rejects | 2, exactly the two guards |
| endpoint stops reporting them | 1 |

`CODES_VERIFIED` untouched; same provenance caveat as #881.

---

## 2026-11-02 — #892 (EPS D1): pin who consumes ips, derived rather than counted

- `tools/pin_ips_consumers.py` (new, in the workspace repo)
- `tools/ips_consumers_baseline.json` (new, committed on purpose)
- `tools/test_pin_ips_consumers.py` (new, 17 checks)
- `results/ips_consumers.json` (generated)
- `plans/eps_state_reform.md` (§3.6 corrected)

**The number was wrong three times in three counts: nine, then eleven, now
TEN.** That is the argument for a tool rather than for a better paragraph —
the same conclusion CLAUDE.md §3 already reached about `KNOWN_SERVICES`, which
was hand-maintained and wrong twice in one week.

Two findings a hand count could not reach:

**`alert.pdhc` is not a consumer.** Its only ips references are two
`os.environ.get` lines in `app/config.py` — no client, no call. Two config keys
nothing reads, so setting or rotating them changes nothing. Same shape as the
SSO External Partner secret that authenticates nowhere.

**The config symbol is not uniform.** `sim.pdhc` uses `IPS_PDHC_BASE_URL` and
`IPS_PDHC_API_KEY` while every other sibling uses `IPS_BASE_URL`, and
`icd11.pdhc` carries eight spellings including `IPS_INTEGRATION_BASE_URL` and
`IPS_AUTH_SCHEME`. A grep for one spelling reports sim as a non-consumer. The
tool therefore DISCOVERS spellings via `IPS[A-Z0-9_]*` instead of taking a
list.

Three rules it follows, each from a measured failure: walk each service
directory explicitly (`grep -r` from the root silently skips every service repo
— ugrep plus a whitelist `.gitignore`); discover the symbol; and attribute
paths only from files that name an ips symbol, which over-attributes when one
file talks to two services and is stated as a limit rather than hidden.

The claim that survives counting entirely is the one about ABSENCE: **no
sibling names a path containing `ips`**, which is what makes #893's rename free
for cross-service calls. The tool asserts it and would report it breaking.

**Widening blocks, narrowing informs** — the same asymmetry as
`check_platform_baseline.py` (#748), for the same reason: a gate that fails on
every removal gets deleted in its first week. A config-only service that starts
CALLING is a widening too, and is reported as such; a membership count alone
would miss it.

`--root` and `--baseline` exist so the gate can be tested against a fixture
tree. **A gate that can only be observed in its passing state has not been
shown to fail.** Proven both ways: 17 fixture checks, plus two live gate tests
against the real workspace (a new consumer injected into onboard, and alert
given a client) which both exited 1 and were then removed with no residue.

**17 ok, 0 failed.** The real tree reads `unchanged against the baseline`,
exit 0.

---

## 2026-11-02 — #895 (EPS C1): the bitemporal patient-state projection

- `gateway/app/models/patient_state.py` (new)
- `gateway/app/services/patient_state.py` (new)
- `gateway/app/models/__init__.py` (registered)
- `gateway/app/__init__.py` (`flask rebuild-patient-state`)
- `gateway/migrations/add_patient_state_facts.sql` (new)
- `gateway/tests/test_eps_patient_state_895.py` (new, 16 tests)

Built to #894 (EPS A2) option c: the write path stays `fhir_resources`,
append-only and already there, and this is a DERIVED projection for reading.
`rebuild_for_patient()` deletes and re-derives, which is what makes it a
projection rather than a second source of truth — if it is wrong, it is
rebuilt, and nothing is lost because nothing originates there.

**Two axes, and the pair is what justifies the table:**

    validity   valid_from / valid_to          when was this TRUE of the patient
    record     recorded_at / recorded_until   when did WE know it

The record axis comes free from `fhir_resources`: `update_resource()` already
writes a new version rather than mutating, so version N's `recorded_until` is
version N+1's `created_at`.

**`valid_from` is NULL for every demographic fact today, and that is the
point.** Measured: the generator writes no `period` on any Patient element.
NULL means *we do not know when this became true* — a different claim from *it
became true when we recorded it*. Filling it from `recorded_at` is the
single-axis mistake, and a control test pins it.

`patient_clinic_assignments` is the ONE source with real validity data after
#891, so it is what demonstrates both axes properly. Its two axes COINCIDE
because the source carries one timestamp — stated in the code and asserted in a
test, so a reader comparing the columns does not conclude the model conflates
them.

**A semantic finding that surprised me, and the test now records it.** FHIR
versioning replaces the WHOLE RESOURCE, not one fact. So *"as known in August,
where did the patient live in January?"* correctly returns NOTHING: the current
record only asserts Nystad from March, and the January belief stopped being
current in July. The earlier belief is still reachable with
`as_known_on=April`. I had asserted the opposite; the code was right and the
test was rewritten to record why.

**Proven on the real backend, not only on SQLite.** The suite runs SQLite,
which stores no timezone — and mixing aware and naive values there does not
merely break an assertion, it corrupts the SQL comparison: `as_at=JANUARY`
matched a fact whose validity starts in MARCH. The test clock is therefore
naive with the reason written in, and all four bitemporal queries were
additionally run against a throwaway `postgres:16-alpine` with `TIMESTAMPTZ`:

    as_at=APR known=APR -> Gamlestad     as_at=JAN known=AUG -> (none)
    as_at=APR known=AUG -> Nystad        as_at=JAN known=APR -> Gamlestad

Same answers on both. A time comparison verified only on SQLite is not
verified.

The migration was also proven against real Postgres: table plus three indexes,
re-run a clean no-op. It carries NO unique constraint on
`(patient_guid, fact_type)` deliberately — the cardinality is 1:N per patient
and 1:1 only per `(patient, fact_type, validity period)`, which is the
operator's correction to the original 1:1 framing.

**829 passed** (813 before). Controls, each with an import check first:

| breakage | red |
|---|---|
| drop the RECORD axis (single-axis store) | 2, the March/July pair |
| fill validity from the record time | 2 |
| make rebuild incremental instead of total | 2 |

**#901 carries what is unwired:** nothing rebuilds the projection
automatically, four of the five existing state bearers are not projected, and
no route exposes the read. Until (a) lands, `patient_state_facts` is empty
unless `flask rebuild-patient-state` is run by hand.

---

## 2026-11-02 — #896 (EPS B7): export selected patients as CSV and as a FHIR Bundle

- `gateway/app/services/patient_export.py` (new)
- `gateway/app/api/patient_routes.py` (`POST /api/v1/patients/export`)
- `gateway/tests/test_eps_patient_export_896.py` (new, 22 tests)

**Nothing like this existed** — measured across ips, cdr and cdr_6: no
`/export` route, no CSV writer, no xlsx writer. So the access and audit
properties were built rather than inherited.

**It is on the API blueprint, not the admin one, and that was measured.**
`admin.py`'s `before_request` checks only for an SSO SESSION and loads **no
user object at all** — not `g.current_user`, not a resolved blob. So on that
surface there is no identity to scope an export by, and the gate would refuse
every request. `@require_auth` on the API blueprint populates
`g.current_user`, which is what the scope rule reads. Filed as **#902**,
with its uncertainty stated, because whether it is exposure depends on what
sso.pdhc will issue a token for — unmeasured.

**Scope is the SAME relationship spärr and consent already use:** admin sees
every requested patient, anyone else sees patients with an ACTIVE
`PatientClinicAssignment` to a clinic they are assigned to. "Active" since
#899(b). A withheld patient is **absent** from the output rather than refused,
so the export leaks no existence either.

And because an export is a SECOND consumer of "may this reader see this
patient", a test compares the set filter against
`blocks_routes._can_act_on_patient` on every candidate and asserts they agree.
Two consumers with different answers is what `care_access_policy`'s "no two
consumers may enforce different zone rules" exists to prevent.

**Personnummer is excluded from the CSV** and carried in the FHIR Bundle. A CSV
leaves the system, `personnummer` is under a hard confinement rule (#405), and
no masking helper exists in this repo — verified. `Patient.identifier` is part
of a FHIR document by design, so that is the deliberate exception.

**Audit is one row per patient, never one per batch.** Fifty patients means
fifty rows; a single "exported a batch" row makes the log useless for the only
question anyone asks of it. And a WITHHELD patient is not audited — an audit
row saying a patient was exported when they were not is worse than none.

**The CSV shape is a decision.** `as_at` (default) gives one row per
`(patient, fact_type)` valid at that date; `history` gives one row per period
with BOTH time axes as columns. No column is called `date`, and a test pins
that: a single `date` column would re-introduce exactly the conflation #895
exists to remove.

The Bundle is R5 (#877) and says so **in the document** — a `meta.tag` of
`not-eps-conformant` with the reason — rather than leaving a recipient to read
a docstring. `version="R4"` raises `UnsupportedFhirVersion` by name, which is
#897's point: the parameter exists so adding R4 later is additive.

Past the cap of 100 (#797's bound) raises `ExportTooLarge`, surfaced as **413
with a code**, not a 500 and not a timeout — the #833 lesson that a permanent
condition reported as transient tells the caller to retry forever.

**851 passed** (829 before). Controls, each with an import check first:

| breakage | red |
|---|---|
| `exportable()` ignores the reader's scope | **4** — incl. the drift guard and the withheld-audit test |
| audit one row per batch | 1 |
| personnummer into the CSV | 1 |
| drop the cap | 2 |

Two of my own assertions were wrong and were corrected rather than the code:
the service must be called inside a request context (the gate reads
`g.current_user`, and calling it with no identity is what the gate is FOR), and
names ARE in the CSV because `name.family` is a state fact — so the scope test
now asserts the allowed patient's data IS present as well as the withheld one's
absent, which is the stronger claim.

---

## 2026-11-02 — #901 (EPS C1b): the state projection wired up

- `gateway/app/services/patient_state.py` (four more sources, `_j()`)
- `gateway/app/models/patient_state.py` (vocabulary 9 -> 16)
- `gateway/app/services/fhir_service.py` (`_refresh_patient_state`)
- `gateway/app/admin.py`, `app/api/clinic_routes.py`,
  `app/services/mock_generator.py` (refresh at the assignment write sites)
- `gateway/app/api/patient_routes.py` (`GET /api/v1/patients/<guid>/state`)
- `gateway/tests/test_eps_state_wired_901.py` (new, 16 tests)

### (a) The trigger rides on a hook that already existed

`_sync_patient_index` runs on every Patient CREATE and UPDATE, so the
projection refresh goes there rather than needing a second hook on the FHIR
write path. Synchronous on purpose: a periodic rebuild makes the projection
eventually-consistent, and "state as at D as known on E" is then answerable
only approximately, which defeats having two axes.

**It never raises into the write path.** A projection is derived data; failing
a clinical write because a read optimisation could not be refreshed is the
wrong trade. The error is logged with the repair command and the write stands.
A test monkeypatches the rebuild to explode and asserts the Patient survives.

The three assignment write sites refresh too, because the Patient hook cannot
see an assignment added afterwards. **A fourth write site would have to as
well** — that is a real drift risk, accepted deliberately over a flush-time
event listener, and a missed site leaves the projection STALE for that patient
rather than wrong, repairable by `flask rebuild-patient-state`.

One bug of my own on the way: the inserted call in `admin.py` referenced
`patient.guid` where only `pi` is in scope — a `NameError` that `py_compile`
cannot see. Found by reading the inserted context rather than trusting the
script that inserted it.

### (b) Four sources, and each lands DIFFERENTLY on the two axes

    source              valid_from    valid_to                  axes distinct?
    patient_consents    granted_at    revoked_at or expires_at  no
    patient_blocks      created_at    lifted_at or expires_at   no
    emergency_access    attested_at   expires_at                YES
    patient_index bools NULL          NULL                      NEITHER
    archived_at         archived_at   NULL                      no

Three findings in that table rather than three choices:

  - **`emergency_access` is the only source with genuinely distinct axes.**
    `attested_at` is when the need was attested; `created_at` is when the row
    was written. Two columns, two meanings, already there before this
    projection existed — so it is the fact type that proves the model is not
    merely carrying one timestamp twice. Pinned by a test asserting the two
    differ.
  - **The two boolean opt-outs have NEITHER axis.** `ehds_opt_out` and
    `quality_registry_opt_out` are bare booleans with no timestamp anywhere,
    so the projection cannot say when the patient opted out or when we learned
    it. NULL/NULL with `date_unrecorded: true` in the value, rather than
    inventing a start from the row's creation. An opt-out whose date is
    unrecorded cannot be audited, and consent withdrawal is exactly the kind
    of fact someone later needs the date of.
  - **A block LIFT is its own fact**, not an attribute of the block: folding it
    in would make "was this block lifted on date D" unanswerable.

Revocation wins over expiry for a consent — revoked before it expired means it
stopped being true when revoked.

### A real bug, found by probing rather than reading

Guid columns on these tables come back as **UUID objects**, and `json.dumps`
refuses a UUID — so the insert failed inside the flush with a traceback naming
the JSON encoder rather than the column. Not a SQLite artefact; it would fail
on Postgres too. Every projector now routes values through `_j()`, and the test
asserts **every** projected value is serialisable rather than checking four
specific fields, so the next projector is covered.

### (c) The read route reuses the scope rule, it does not copy it

`GET /api/v1/patients/<guid>/state?as_at=&as_known_on=`, scoped through
`patient_export.exportable` — the same question the export asks. There were
already two implementations of that predicate (the per-patient gate in
`blocks_routes`, the set filter in `patient_export`) with a test asserting they
agree; a third would be one too many.

Out of scope returns **404, not 403**: a 403 confirms the guid exists. The
response echoes `as_at` and `as_known_on` so a default-to-now answer is
distinguishable from an explicit one, and says `projection.derived: true` with
the repair command, so a caller who gets an empty answer knows whether to
suspect the data or the rebuild.

**867 passed** (851 before). Controls, each with an import check first:

| breakage | red |
|---|---|
| no trigger on Patient write | 3 |
| a failing refresh raises into the write | 1 |
| drop the four new sources | 4 |
| remove the JSON coercion | 6 |
| out-of-scope returns 403 | 1 |

**Noticed on the way:** the LOCAL dev Postgres has no `ehds_opt_out` column —
it is behind on `add_reform_patient_flags.sql` (#404). Nothing was written to
it; the probe's transaction aborted. Worth running before anyone tests the
opt-out projection against dev.

---

## 2026-11-02 — #900 (EPS C4c): the write path that can END an assignment

- `gateway/app/services/patient_assignment.py` (new)
- `gateway/app/api/patient_routes.py` (two routes)
- `gateway/tests/test_eps_assignment_write_900.py` (new, 21 tests)

**This closes a chain that was otherwise inert.** #891 gave the schema an
`ended_at` and the partial unique index; #899(b) made spärr, consent and care
access honour it; #901 made the state projection follow it. Nothing could SET
it, so all three guarded a state that never occurred.

### Two operations, not one

    POST /api/v1/patients/<guid>/assignments                     open one
    POST /api/v1/patients/<guid>/assignments/<clinic>/end        close one

`assign` refuses an OPEN duplicate and ALLOWS a closed one, because "left and
came back" is exactly the case #891's partial index exists for. The refusal is
a **named error with its own code**, not an `IntegrityError`: the database
would refuse it too, but as a 500 carrying a constraint name, which tells a
caller nothing about what to do. Each refusal gets a distinct code —
`already_assigned` and `not_assigned` need different actions and a shared code
would make them indistinguishable in a client log.

### The first writer of validity time, and two refusals that follow

`ended_at` defaults to now and **accepts a past date**, because learning of a
move after the fact is the ordinary case. It is not `utcnow()` only — that is
the single-axis mistake #895 exists to prevent, and this is where the platform
first had to have an opinion.

Two bounds, both refusals rather than silent coercions:

  - **`ended_at` before `assigned_at`** — an interval that ends before it
    begins is not a bad date, it is an impossible fact.
  - **A FUTURE `ended_at`** — a planned future end is an EXPIRY, and #891's
    model note is explicit that `ended_at` is not `expires_at`: an expiry in
    the future means "still valid" while a non-NULL `ended_at` always means
    "over". Accepting a future date would make that distinction false for
    every consumer reading it. This refusal was not in the ticket; it follows
    from #891's own reasoning.

### Who may change it is NARROWER than who may read the patient

Admin, or staff assigned to **the clinic being changed**. Deliberately not
"may see the patient": ending an assignment removes access for everyone at that
clinic, so being able to read a patient is not reason enough to detach them
from a clinic you have nothing to do with.

### The tz comparison was normalised on purpose

SQLite stores no timezone, so a stored value reads back naive while
`datetime.now(timezone.utc)` is aware, and comparing them raises. `_naive_ok`
normalises so the RULE is identical on both backends rather than accidentally
skipped on one — the #895 lesson, where a tz mismatch silently corrupted a
comparison instead of failing.

### Audit says the CONSEQUENCE, not just the fact

The end row carries `effect: "staff at this clinic lose spärr, consent and
care access for this patient"` and a `backdated` flag. Someone reading the log
cares that access was removed, not only that a timestamp was written.

**888 passed** (867 before). Controls, each with an import check first:

| breakage | red |
|---|---|
| `end()` DELETES instead of setting `ended_at` | 6 |
| accept a FUTURE `ended_at` | 2 |
| let the DB raise instead of a named refusal | 2 |
| anyone may change any clinic | 1 |

`TestItMakes899Live` is the one that matters: it asserts
`consents_routes._can_act_on_patient` goes True -> False across an `end()`, the
patient leaves the clinic roster, and the state projection's
`clinic_assignment` fact closes. **That is the first time #899(b)'s narrowing
has had any effect.**

---

## 2026-11-02 — #886 (EPS B6): alert.pdhc's implant selection as FHIR

- `gateway/app/services/alert_implants.py` (new)
- `gateway/tests/test_eps_alert_implants_886.py` (new, 18 tests)

**No HTTP client, deliberately — and that is a measurement, not a shortcut.**
alert.pdhc runs nowhere: no container locally, none on miserver, no
`/usr/local/www/alert.pdhc`, zero mentions in CLAUDE.md's service table. It is
buildable and not deployed. A client against it would reproduce the xlate
defect (#833): a default base URL manufactures a configured-looking service out
of an unset variable, so "nobody wired this up" becomes indistinguishable from
"it blipped". The transport is **#903**.

The direction is already implied by configuration: alert carries
`IPS_BASE_URL` and `IPS_API_KEY` and never calls them (#892 found them as
config nothing reads), so the intended wire is alert PUSHING here.

### The national term is load-bearing, and the code cannot carry it

From alert's own `registration.py`: *"Twelve codes bind two or three … `Z95.0`
in `Förekomst av implantat` covers ICD, pacemaker AND pacemaker electrode … a
record holding only the code cannot say what the clinician picked."*

So a mapping that fills `Device.type.coding` and drops `national_term` loses
WHICH device was selected — a clinical loss, not a formatting one. It goes in
`Device.type.text`, because FHIR defines `CodeableConcept.text` as the
representation *as seen and selected by the user*, which is exactly what a
national term is. A test asserts two assertions sharing `Z95.0` stay
distinguishable.

### `negation` is the ABSENT case, not a Device with a flag

`negation` means it has been ESTABLISHED the patient does not have it. That maps
to the section's own `no-known-devices` absent code — and the strongest test
asserts `status_for_resources` then reads **EXPLICITLY_ABSENT**, which under
EPS's 1..1 is the difference between a filled mandatory section and a
conformance failure. A Device carrying a flag would make every consumer see an
implant that is not there.

### `asserted_at`, never `recorded_at`

alert keeps the two apart for the same reason #895 does. A `DeviceUsage` timing
is a clinical fact about the patient; the record time would date every implant
to the day it was imported.

### Simulated stays distinguishable, on every path

`provenance` (`documented` | `simulated`, enforced by a check constraint in
alert) survives into `meta.tag` — including on the negated path, which has
fewer resources and is where a marker is most easily dropped. This is the
MDR-relevant surface `euips_sections`'s alerts note already warns about.

The Socialstyrelsen specification is cited, never reproduced: the selection is
named and codes are read from alert's own rows.

**906 passed** (888 before). Controls, each with an import check first:

| breakage | red |
|---|---|
| drop the national term | 2 |
| use `recorded_at` for the timing | 1 |
| emit a Device for a NEGATED assertion | 2 |
| drop the provenance marker | 2 |

Also checked and found harmless: `provenance="computed"` appears in alert's
code and would violate its own check constraint — it is in a TEST, asserting
the constraint refuses it.

---

## 2026-11-02 — #897 (EPS A1b): the version parameter, and a defect it predicted

- `gateway/app/services/patient_export.py` (deep copy)
- `gateway/tests/test_eps_patient_export_896.py` (one test added)

Three of #897's four asks were already satisfied by #896 and are confirmed
rather than rebuilt:

| ask | state |
|---|---|
| the export renders R5 | done (#896) |
| the renderer takes the version as a PARAMETER, R4 refused by name | done — `UnsupportedFhirVersion` |
| advertised as an operation, not a conformance claim | the CapabilityStatement mentions no export and makes no conformance claim; the Bundle carries `not-eps-conformant` in its own `meta.tag` |
| **render into a NEW dict; never mutate** | **was NOT satisfied — fixed here** |

### The defect #897 named in advance and #896 shipped anyway

`to_fhir_bundle` put `r.resource_json` — the ORM object's own dict — into the
bundle **by reference**. Measured: setting a key on a bundle entry appeared on
the stored `resource_json`, and if that object is later flushed the mutation is
PERSISTED. An export is a read; it must not be able to write.

It is also the precondition for ever adding an R4 renderer: a downgrade editing
in place would corrupt the R5 output it was derived from, which is the reason
#897 asked for it before any R4 work existed.

### My first test for it could not fail

I asserted the consequence — mutate the bundle, check the stored row is
unchanged — and it passed **with and without the fix**. Whether a mutation
propagates depends on session state: `_patient()` commits, which expires the
object, so the next query reloads a fresh dict. A control that cannot fail is a
guard that proves nothing, and the only reason it was caught is that the
control was run at all.

Rewritten to assert the **property** instead: `entry["resource"] is not
stored.resource_json`. Identity cannot pass accidentally. The mutation check is
kept as a secondary assertion.

**907 passed** (906 before). Control: revert the deep copy -> 1 red.

---

## 2026-11-02 — #888 (EPS C2): address, contact and telecom with real periods

- `gateway/app/services/euips_header.py` (`patient_address`, period helpers,
  the contact mirror)
- `gateway/app/services/mock_generator.py` (full address + telecom period)
- `gateway/tests/test_eps_address_periods_888.py` (new, 16 tests)

Before this the generator wrote `use`, `city` and `country`. A service meant to
hold "all state information about a patient" could not say what street they
live on, and **had no validity period anywhere** — so every demographic fact in
the state projection (#895) carried `valid_from = NULL`: honest, and useless
for answering "where did this patient live in March".

### The payoff, asserted end to end

`TestThePayoff` is what makes this ticket worth anything. It asserts the
projection's address facts now carry a real `valid_from`, that `address.line`
and `address.postalCode` appear at all, and — the part that proves the period
is doing work rather than decorating — that an `as_at` read **before** the move
excludes the address while one **after** includes it. The second half is the
control: without it, an as-at read that returned nothing would pass the first.

### Three coherence rules, each a refusal rather than a default

  - **The city is passed in, never redrawn.** It determines the Coverage
    insurer's region (#792); drawing it inside would put a Stockholm resident
    on Region Skåne's books.
  - **The postcode's leading block follows the city.** A postcode contradicting
    the city is the sort of incoherence that makes a cohort useless for testing
    a real integration.
  - **No period unless one is given.** A period must be data, not a default —
    an invented start is the single-axis mistake #895 refuses.

A start before the patient was born is an impossible fact, not a bad date — the
same reasoning #900 applies to `ended_at` before `assigned_at` — so the lower
bound is derived from the birth year. A degenerate range (born last year, "moved
in at 18") is clamped rather than raising, and the property that survives is
that the date is still in the PAST.

### The contact mirror carries the period, or the two copies can disagree

`RelatedPerson` and the inline `Patient.contact` are generated from ONE list
precisely so they cannot disagree. A period on the resource but not on the
inline copy would be exactly that disagreement — with the inline copy being the
one most consumers read.

### A test of mine was a tautology, and the control caught it

`test_a_start_is_after_birth_and_in_the_past` asserted
`got >= birth+18 OR got <= this_year`. The second branch is true for every past
date, so the whole thing was vacuous: the control that let the start be drawn
from 1900 **passed it**. Replaced with a conjunction that handles the
degenerate range explicitly.

That is the second time in this session a control caught a test that could not
fail — #897's mutation test was the first. Both were found only because the
control was run rather than assumed, which is the argument for running them at
all.

Street names are deliberately among the most common in Sweden and exist in
hundreds of municipalities: plausible in shape, resembling no particular real
address. The same judgement #792 applied to a contact's surname.

**923 passed** (907 before). Controls, each with an import check first:

| breakage | red |
|---|---|
| the generator writes no period | 3 |
| the contact mirror drops the period | 1 |
| postcode drawn independently of the city | 1 |
| allow a start BEFORE birth | 1 — *after the tautology was fixed; 0 before* |
