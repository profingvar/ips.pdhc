# #437 — prod ips full reconcile runbook (prepared 2026-07-10)

Everything below is verified against prod as of 2026-07-10. The ONLY
remaining gate is the **legal sign-off on the patient-facing spärr copy
(#242)** — when that lands, the flip is the ~10 commands in §4.

## 1. What prod is (verified)

`/usr/local/www/pdhcips` — flat dir, NOT git. Prod = an old base
(≈ commit `965e825`-era) + the surgical overlays shipped since
(#433 D1+#422 3-file, D3 #406 3-file + 2-line registrations).

- **Zero prod-only content**: every prod file byte-matches SOME commit
  in origin/main history (re-verified 2026-07-10). Nothing to mirror
  back.
- **Schema is COMPLETE**: all 16 tables exist (incl. `patient_consents`,
  `patient_blocks`, `emergency_access`) and the three D1 flags are on
  `patient_index` — startup `create_all` has kept new tables current,
  and the flag ALTERs shipped with #433. **No DB work is needed for the
  reconcile.**

## 2. The divergence (exact, 2026-07-10, origin/main = a24485b+)

**Missing on prod (~25 files)** — the #199/#200/#245 patient-portal
self-consent/self-block feature set + admin lift UI + copy bundle:
`patient_portal.py`, `admin_block_lift.py`, `api/patient_blocks_routes.py`,
`api/patient_consents_routes.py`, `api/copy_routes.py`,
`services/sparr_copy.py`, `copy/sparr_copy.json`, 11 templates
(`patient_*`, `admin_block_lift_*`, `_patient_portal_banners.html`),
`docs/sparr_operator_runbook.md`, `docs/sparr_zones.md`, `docs/technical.md`.

**Stale on prod (9 files, each byte-matches an older commit — safe to
overwrite):** `config.py` (=ffcf7f6), `api/health.py` (=8d35391),
`api/admin_blocks_routes.py` (=61d415b), `fhir/fhir_routes.py` +
`templates/docs_api.html` (=ff1c959), `templates/docs_manual.html` +
`docs_technical.html` (=3636402), `services/auth_service.py` (=965e825),
`services/block_webhook.py` (=ffcf7f6).

**Replaced by origin (2 files):** `app/__init__.py`, `app/models/__init__.py`
— prod versions are old-base + the D3 2-line patches; origin's versions
contain those registrations plus the portal/copy/consent blueprints.

## 3. The legal caveat (why this is gated)

The catch-up activates the patient-facing spärr copy (commit `0e024ae`
family, tracked #242) and the patient portal that renders it. Nothing
else in the bundle is sign-off-gated. Note the portal code carries a
`copy_approved` metadata gate — confirm the copy bundle's approval flag
reflects the actual sign-off before flipping.

## 4. The flip (run AFTER #242 sign-off)

```bash
# on the Mac
cd ~/T7_sidewinder/ips.pdhc && git archive origin/main gateway docs \
    -o /tmp/ips_437.tar && scp /tmp/ips_437.tar miserver@192.168.1.154:/tmp/

# on miserver
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
docker context use colima
DBC=$(docker ps --format '{{.Names}}' | grep ips-db)
docker exec $DBC pg_dump -U "$(docker exec $DBC printenv POSTGRES_USER)" \
    -d "$(docker exec $DBC printenv POSTGRES_DB)" -Fc -f /tmp/pre437.pgdump </dev/null
docker cp $DBC:/tmp/pre437.pgdump ~/backups/predeploy/ips.pdhc/pre_437_$(date -u +%Y%m%dT%H%M%SZ).pgdump
cd /usr/local/www/pdhcips
tar -czf ~/backups/predeploy/ips.pdhc/pre_437_src_$(date -u +%Y%m%dT%H%M%SZ).tgz gateway/app docs
docker tag ips-app:latest ips-app:pre_437
tar -xf /tmp/ips_437.tar -C .           # full overlay — .env untouched (not in git)
cd gateway && docker-compose up -d --build app
# verify
curl -s http://127.0.0.1:9040/api/v1/health          # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9040/patient/blocks  # portal live (302/401, not 404)
```

Rollback: `docker tag ips-app:pre_437 ips-app:latest` + re-extract the
pre_437_src tar + `docker-compose up -d --build app`.

## 5. After the flip

- Consider converting `/usr/local/www/pdhcips` to a git checkout (the
  cdr.pdhc git-ification 2026-07-08 is the template: init → fetch →
  reset -q origin/main → per-file verify) so future deploys are
  ff-merges.
- The D3 emergency-access portal banner activates with the portal — it
  reuses the same copy-bundle mechanism; confirm its copy key is in the
  signed-off bundle or add it to the #242 review scope.
