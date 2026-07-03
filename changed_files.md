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
