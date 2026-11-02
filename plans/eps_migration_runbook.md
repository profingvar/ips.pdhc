# EPS migrations — production runbook

> **ALL THREE APPLIED TO PRODUCTION 2026-11-02T16:57Z and verified.** The
> account below is kept as the runbook it was; what actually happened is in
> `progress.md`. Re-running any of them is safe — all three are idempotent.
>
> Dump taken first: `~/backups/predeploy/ips.pdhc/pre_eps_2026-11-02T16-56-56Z.sql`,
> 7.9 MB, completion marker present, COPY blocks for
> `patient_clinic_assignments`, `patient_index` and `fhir_resources`.

Three migrations from the 2026-11-02 EPS work are applied to the LOCAL dev
database only. This is what running them on production needs, in order, with
the verification that makes each step checkable rather than hopeful.

Written because the alternative is reconstructing it from three tickets and a
git log at the moment of running it, which is the worst time.

**Operator-gated.** Platform CLAUDE.md §14/§15: Claude may do a graceful
restart of the service in scope and nothing else. These are schema changes on
a live clinical database.

---

## 0. Before anything

```bash
# a predeploy dump, in the place the platform expects it
ssh miserver 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; \
  mkdir -p ~/backups/predeploy/ips.pdhc && \
  docker exec ips-db-1 pg_dump -U ips_user ips_db \
    > ~/backups/predeploy/ips.pdhc/pre_eps_$(date -u +%Y-%m-%dT%H-%M-%SZ).sql'
```

Verify it is non-empty before continuing. A backup whose `cp` failed silently
is how originals get zeroed (`feedback_root_owned_dirs_backup_pattern`).

---

## 1. `add_assignment_ended_at.sql` (#891)

**The only one that is not purely additive.** It drops a unique constraint.

Order inside the file is load-bearing and already correct: the new partial
index is created BEFORE the old constraint is dropped, so the table is never
without uniqueness on that pair.

The old constraint is **looked up by its COLUMNS, not by name**. Both local and
production named it `uq_patient_clinic_assignments_patient_guid` rather than the
Postgres default, so a hardcoded `DROP CONSTRAINT` would have silently done
nothing and left "ended" terminal per pair.

```sql
-- before: what is there now
SELECT c.conname, c.contype FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
 WHERE t.relname = 'patient_clinic_assignments';
SELECT count(*) AS rows, count(ended_at) AS already_ended
  FROM patient_clinic_assignments;   -- errors if the column is absent: expected
```

Apply, then:

```sql
-- after: the partial index exists and the old constraint is gone
SELECT indexname FROM pg_indexes
 WHERE tablename = 'patient_clinic_assignments';      -- expect uq_patient_clinic_active
SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
 WHERE t.relname = 'patient_clinic_assignments' AND c.contype = 'u';  -- expect 0
```

It is idempotent: a second run raises `NOTICE: no (patient_guid, clinic_guid)
unique constraint found — already migrated`.

**What changes behaviour:** three authorisation paths — spärr, consent and care
access — were narrowed to ACTIVE assignments by #899b. On the day it shipped
`ended_at` was NULL on all 296 production rows and no write path could set one,
so the narrowing changed no real answer. After #900 something can set it.

---

## 2. `add_patient_state_facts.sql` (#895)

Purely additive: one new table.

```sql
SELECT count(*) FROM patient_state_facts;   -- expect 0 after the migration
```

**The projection is EMPTY until rebuilt**, which is deliberate and is the open
half of #895:

```bash
flask rebuild-patient-state          # every patient
flask rebuild-patient-state --patient <guid>
```

Safe to run at any time: every row is derived from `fhir_resources` or
`patient_clinic_assignments`, and the command deletes and re-derives rather
than patching. Nothing originates there, so nothing can be lost by rebuilding.

---

## 3. `add_patient_proxy_grants.sql` (#889)

Purely additive: one new table.

Note deliberately **no** unique constraint over (patient_guid,
proxy_user_guid). A plain UNIQUE would make revocation terminal for that pair
for ever (#891's lesson); "only one ACTIVE grant per pair" is enforced at the
API layer, as `patient_blocks` and `patient_consents` already do it.

```sql
SELECT count(*) FROM patient_proxy_grants;   -- expect 0
SELECT indexname FROM pg_indexes WHERE tablename = 'patient_proxy_grants';
-- expect ix_patient_proxy_grants_patient and ix_patient_proxy_grants_proxy
```

Nothing grants anything until a patient does. The surface refuses an
unknown proxy by default — the whole point of #889's design.

---

## 4. After all three

```bash
curl -s https://ips.pdhc.se/api/v1/health      # 200, database connected
```

And the thing a green health check does NOT tell you: whether the deployed
code matches this checkout. ips's container has been ahead of its release
directory before (`feedback_container_ahead_of_release_dir`), and the gate
added by #902 only takes effect on the next deploy. **Diff before deploying
code**, separately from these migrations.

---

## 5. NOT part of this runbook

- **#908's `flask migrate-r5-device-elements`** edits stored clinical JSON.
  Dry run by default. Its gate is "before #905 wires real implant data", not
  now — see `eps_state_reform.md`.
- **The #902 admin gate** takes effect on the next ips code deploy.
  `IPS_ADMIN_REQUIRE_ANALYSIS_PHASE` stays unset, so the phase half
  shadow-logs rather than refuses. Flip it when the log is quiet.
- **#874's cdr1 assertion gate** is a different service and a different
  release, with its own operator-only service key.
