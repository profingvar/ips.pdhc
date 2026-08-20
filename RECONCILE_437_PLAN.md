# ips.pdhc prod reconciliation — plan & runbook (#437)

**Status:** prepared 2026-08-20, both blockers cleared, ready to execute.
**Owner action required:** operator runs the deploy (personnummer/PII service).

---

## 1. Why this exists

Prod ips (`/usr/local/www/pdhcips`, container `ips-app-1`, image `ips-app`,
compose service `app`, port 9040) has drifted **behind** `origin/main`. It is a
flat directory, **not** a git checkout. The `#199/#200/#245` patient-portal
self-consent / self-block feature set and the `#349` rollup were completed as
tickets but never fully deployed here. `#433` shipped only a 3-file surgical
overlay on purpose, because activating unsigned patient-facing legal copy on a
PII service was not allowed.

**Both blockers are now clear:**
- **(a) Legal** — the spärr patient-facing copy is legally approved (#242,
  commit `fb328c5`; `sparr_copy.is_legally_approved()` → True).
- **(b) DB schema** — verified ready (see §3).

---

## 2. What the reconciliation actually is (verified 2026-08-20)

A **source-only** catch-up of `gateway/app/` to local HEAD `fb328c5`
(= `origin/main` `d8b6dbb` + the #242 sign-off). Measured against prod:

| Category | Count | Action |
|---|---|---|
| Already current (== HEAD) | 34 | none |
| Cleanly behind (matches an older commit) | 5 | updated |
| **New modules to add** | **7** | `patient_consents_routes`, `patient_blocks_routes`, `copy_routes`, `admin_block_lift`, `patient_portal`, `sparr_copy`, `copy/__init__` |
| Empty `__init__.py` (false-positive md5 flags) | 3 | benign |
| **Server-only functional edits** | **0** | — |
| Extra files in prod (would be lost) | 0 | — |

- The only prod-unique content **anywhere** is a single **comment** line in
  `app/__init__.py`. So prod is a **clean subset** of origin — safe to overwrite.
- The `auth_service.py.bak-2026-04-15` file was a false alarm: that edit was
  already reconciled into git; prod's `auth_service.py` matches a commit.
- `requirements.txt` is **identical** — no new dependencies.

---

## 3. DB readiness (part b) — no migration needed

ips uses SQLAlchemy `create_all` (no alembic). `create_all` **creates missing
tables but never adds columns / alters**. Verified against prod `ips_db`:

- Tables present: `patient_blocks`, `patient_consents`, `emergency_access`
  (+ 13 others).
- **Column-level check**: prod's tables cover origin's models **exactly** —
  no column that origin's models expect is missing.

So the deploy needs **no schema change**. Personnummer/Q5 lives in
`patient_index`, untouched by this deploy.

---

## 4. Deploy steps (what the script does)

Script: `scratchpad/reconcile_ips_437.sh`, run **from the Mac**.

1. **Preflight** — abort if the local tree is dirty; print HEAD (expect
   `fb328c5`); tar `gateway/app` (excluding caches).
2. **Ship** — scp the tarball to the server.
3. **Backup (on server)** — to `~/backups/predeploy/ips/`:
   - `ips_prod_app_<stamp>.tgz` — current prod `app/` (rollback target).
   - `ips_db_<stamp>.sql.gz` — full `pg_dump` of `ips_db`.
4. **Replace** — `rm -rf app/` then extract the new `app/`.
   **`.env`, `docker-compose.yml`, `start.sh` are NOT touched** (prod config /
   gitignored secrets stay).
5. **Rebuild + recreate** — `docker-compose build app` + `up -d --no-deps app`.
6. **Verify** — health 200; the 7 new modules import; `is_legally_approved()`
   is True.
7. **Auto-rollback on any failure** — restore `app/` from the backup tar and
   rebuild. The DB dump is kept regardless.

**Note:** deploys **local `fb328c5`**, not `origin/main` — deliberate, because
origin doesn't yet carry the #242 sign-off (push pending). Functionally
identical to origin + the approved copy.

---

## 5. Manual rollback (if ever needed after the fact)

```
BK=~/backups/predeploy/ips
# source:
rm -rf /usr/local/www/pdhcips/gateway/app
tar xzf $BK/ips_prod_app_<stamp>.tgz -C /usr/local/www/pdhcips/gateway
cd /usr/local/www/pdhcips/gateway && docker-compose build app && docker-compose up -d --no-deps app
# db (only if a data problem — this deploy makes no schema change, so usually NOT needed):
gunzip -c $BK/ips_db_<stamp>.sql.gz | docker exec -i ips-db-1 psql -U ips_user -d ips_db
```

---

## 6. Effort split — pickable tickets (do 1 by 1)

- **T1 — Reconcile prod ips source (the deploy).** Run §4. Atomic, backed-up,
  auto-rollback. *Do first.*
- **T2 — Functional smoke of the activated patient surfaces.** Beyond T1's
  import/health check: exercise patient-portal **self-block create**, **block
  list**, **self-consent grant/revoke**, and confirm the **indispensable-care
  notification** + spärr copy render with the approved (v1.0.0) wording.
- **T3 — Push the #242 sign-off to origin.** `git push` `fb328c5` so the legal
  audit trail is on GitHub (currently local-only).
- **T4 — Re-home #212 admin off-org read gate.** Now unblocked (this was #471
  item 2). Design + implement the care-delivery-appropriate admin-read
  justification control (break-glass / nödöppning style), audited via
  `@audit_read`.

T1 first; T2 after T1; T3 anytime; T4 after T1.
