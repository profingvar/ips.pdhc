#!/usr/bin/env bash
# ============================================================
# ips.pdhc — euIPS #791 (section catalogue, batch column, computed status endpoint).
#
#   ./deploy_789.sh            # compare only. Writes NOTHING.
#   ./deploy_789.sh --apply
#
# Bundle paths are relative to ips's live root, which is
# /usr/local/www/pdhcips/gateway -- NOT /usr/local/www/ips.pdhc, which does not
# exist. Resolved from the container's compose label rather than assumed,
# because a hardcoded guess was wrong here once before (#730).
#
# Note there is also a stale nested copy at
# /usr/local/www/pdhcips/pdhcips/gateway/. It is NOT what runs; this script
# touches only the path the container reports.
#
# The question before writing is "does the server still match what I started
# from", not "does it differ from my new file". baseline/ holds the pre-change
# copies from git 711b669.
# ============================================================
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
docker context use colima >/dev/null 2>&1 || true

MODE="${1:---check}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$HOME/backups/predeploy/ips.pdhc/$TS"

LIVE="$(docker inspect ips-app-1 --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
[ -n "$LIVE" ] && [ -d "$LIVE" ] || { echo "ERROR: cannot resolve ips-app-1 working_dir (got '${LIVE:-empty}')"; exit 2; }
[ -d "$LIVE/app" ] || { echo "ERROR: $LIVE/app missing — layout is not what this expects"; exit 2; }

echo "live root : $LIVE"
echo "bundle    : $SRC"
echo "mode      : $MODE"
echo

DIFFER=0; DRIFT=0; MISSING=0
while read -r f; do
  [ -n "$f" ] || continue
  new="$SRC/new/$f"; old="$LIVE/$f"; base="$SRC/baseline/$f"
  if [ ! -f "$new" ]; then echo "MISSING-NEW    $f"; MISSING=1; continue; fi
  if [ ! -f "$old" ]; then
    if [ -f "$base" ]; then echo "NEW-ON-SERVER  $f  (in git at baseline; server behind)"
    else echo "NEW-FILE       $f  (new in this change)"; fi
    DIFFER=1; continue
  fi
  h_new="$(shasum -a 256 "$new"|cut -d' ' -f1)"; h_old="$(shasum -a 256 "$old"|cut -d' ' -f1)"
  h_base=""; [ -f "$base" ] && h_base="$(shasum -a 256 "$base"|cut -d' ' -f1)"
  if   [ "$h_new" = "$h_old" ]; then echo "IDENTICAL      $f  (already deployed)"
  elif [ -z "$h_base" ];       then echo "NO-BASELINE    $f"; DRIFT=1
  elif [ "$h_old" = "$h_base" ]; then
       echo "SAFE-REPLACE   $f  ($(wc -c <"$old"|tr -d ' ') -> $(wc -c <"$new"|tr -d ' ') bytes)"; DIFFER=1
  elif grep -q "^$f	" "$SRC/ACCEPT_STALE" 2>/dev/null; then
       echo "STALE-ACCEPTED $f"
       echo "               $(grep "^$f	" "$SRC/ACCEPT_STALE" | cut -f2)"; DIFFER=1
  else echo "*** DIFFERS FROM BASELINE ***  $f"
       echo "               server is either AHEAD (edited there, never committed)"
       echo "               or merely BEHIND. This check cannot tell which."
       echo "               '<' my baseline, '>' the server:"
       diff "$base" "$old" | head -25 | sed 's/^/               /' || true; DRIFT=1
  fi
done < "$SRC/FILES"
echo

[ "$MISSING" = "0" ] || { echo "ABORT: bundle incomplete. Nothing changed."; exit 3; }
if [ "$DRIFT" = "1" ]; then
  echo "ABORT: a server file is not what I started from. Nothing changed."
  echo "If the server is AHEAD, reconcile into git. If merely BEHIND, verify no"
  echo "server-only content is lost and record what you checked in ACCEPT_STALE."
  exit 6
fi
[ "$DIFFER" = "1" ] || { echo "Nothing to do — server already matches."; exit 0; }
if [ "$MODE" != "--apply" ]; then
  echo "Compare only. NOTHING was written."
  echo "  ./deploy_789.sh --apply"
  exit 0
fi

# ORDERING GATE. The new model selects generation_batch_guid, so shipping this
# code before the column exists makes EVERY PatientIndex query fail -- a total
# outage of the service nine siblings depend on. Refuse rather than trust that
# the migration was remembered.
HAS_COL="$(docker exec ips-db-1 psql -U ips_user -d ips_db -At -c "SELECT count(*) FROM information_schema.columns WHERE table_name='patient_index' AND column_name='generation_batch_guid';" 2>/dev/null || echo 0)"
if [ "$HAS_COL" != "1" ]; then
  echo "ABORT: patient_index.generation_batch_guid does not exist yet."
  echo "The new model selects it, so this code would fail every patient query."
  echo "Run migrations/add_generation_batch_guid.sql first. Nothing changed."
  exit 7
fi
echo "ordering gate: generation_batch_guid exists — safe to ship the model"
echo

echo "Backing up to $BACKUP"
mkdir -p "$BACKUP"
while read -r f; do
  [ -n "$f" ] || continue
  if [ -f "$LIVE/$f" ]; then mkdir -p "$BACKUP/$(dirname "$f")"; cp -p "$LIVE/$f" "$BACKUP/$f"; fi
done < "$SRC/FILES"
echo "Backed up $(find "$BACKUP" -type f | wc -l | tr -d ' ') file(s)."
echo

while read -r f; do
  [ -n "$f" ] || continue
  mkdir -p "$LIVE/$(dirname "$f")"; cp "$SRC/new/$f" "$LIVE/$f"; echo "copied  $f"
done < "$SRC/FILES"
echo

PYFAIL=0
for f in $(grep '\.py$' "$SRC/FILES"); do python3 -m py_compile "$LIVE/$f" || PYFAIL=1; done
if [ "$PYFAIL" = "1" ]; then
  echo "ERROR: a Python file does not compile. Restoring."
  while read -r f; do [ -f "$BACKUP/$f" ] && cp -p "$BACKUP/$f" "$LIVE/$f"; done < "$SRC/FILES"
  echo "Restored. Service untouched."; exit 4
fi
echo "py_compile OK"
echo

DC="docker compose"; command -v docker-compose >/dev/null 2>&1 && DC="docker-compose"
echo "Rebuilding ips-app-1 (Dockerfile does COPY . ., so --build is mandatory) ..."
( cd "$LIVE" && $DC up -d --build app )
echo

echo "Waiting for health ..."
for i in $(seq 1 30); do
  if curl -fsS https://ips.pdhc.se/api/v1/health >/dev/null 2>&1; then
    echo "HEALTHY: $(curl -fsS https://ips.pdhc.se/api/v1/health)"; break; fi
  sleep 2
  [ "$i" = "30" ] && { echo "WARNING: no health in 60s"; docker logs --tail 40 ips-app-1
    echo "Roll back: cp -rp $BACKUP/app $LIVE/app && (cd $LIVE && $DC up -d --build app)"; exit 5; }
done
echo

echo "=== in-container verification ==="
docker exec ips-app-1 sh -c 'test -f /app/app/services/euips_sections.py && echo "  euips_sections.py: present" || echo "  euips_sections.py: *** MISSING ***"'
docker exec ips-app-1 python -c "
import sys; sys.path.insert(0, '/app')
from collections import Counter
from app.services import euips_sections as es
print('  sections: %d  %s' % (len(es.SECTIONS), dict(Counter(s.obligation for s in es.SECTIONS))))
print('  required: %s' % (es.REQUIRED_KEYS,))
print('  CODES_VERIFIED: %s  (must be False until the IG is checked)' % es.CODES_VERIFIED)
"
echo
echo "  the new endpoint against a real patient (read-only):"
docker exec ips-app-1 python -c "
import sys; sys.path.insert(0, '/app')
from app import create_app
from app.models.base import db
from app.models.patient_index import PatientIndex
from app.models.fhir_resource import FhirResource
from app.services import euips_sections as es
app = create_app()
with app.app_context():
    total = db.session.query(PatientIndex).count()
    conformant = 0
    missing_all = 0
    for p in db.session.query(PatientIndex).all():
        rows = db.session.query(FhirResource).filter(
            FhirResource.patient_guid == p.guid).all()
        st = es.status_for_resources(rows)
        if es.is_conformant(st):
            conformant += 1
        if all(v == es.MISSING for v in st.values()):
            missing_all += 1
    print('    patients: %d' % total)
    print('    euIPS-conformant (all 3 required present or explicitly absent): %d' % conformant)
    print('    no content in ANY section: %d' % missing_all)
    print('    => the Phase C baseline, measured in production')
"
echo
echo "  the batch column, as the model sees it:"
docker exec ips-app-1 python -c "
import sys; sys.path.insert(0, '/app')
from app import create_app
from app.models.base import db
from app.models.patient_index import PatientIndex
app = create_app()
with app.app_context():
    n = db.session.query(PatientIndex).count()
    b = db.session.query(PatientIndex).filter(
        PatientIndex.generation_batch_guid.isnot(None)).count()
    print('    %d patients, %d with a batch guid (expected 0)' % (n, b))
"
echo
echo "Done. Backup: $BACKUP"
echo "Roll back: cp -rp $BACKUP/app $LIVE/app && (cd $LIVE && $DC up -d --build app)"
echo "NOTE: the migration is already applied and is NOT undone by that rollback."
echo "      The column is nullable with no default, so the previous code"
echo "      ignores it; DROP COLUMN generation_batch_guid only if truly needed."
