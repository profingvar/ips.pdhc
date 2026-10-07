#!/usr/bin/env bash
# ============================================================
# ips.pdhc — euIPS #796 (the three EU additions + two discriminator subtractions).
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
# copies from git cf4ff35.
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

# No ordering gate: #793 adds no column. The #791 migration is already
# applied, and nothing here reads a new one.

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
docker exec ips-app-1 sh -c 'test -f /app/app/services/euips_eu_additions.py && echo "  euips_eu_additions.py: present" || echo "  *** MISSING ***"'

docker exec ips-app-1 python -c "
import sys, random; sys.path.insert(0, '/app')
from app.services import euips_eu_additions as eu, euips_optional as opt, euips_sections as es
class R:
    def __init__(s, t, j): s.resource_type, s.resource_json = t, j

print('  TRAVEL_CODES: %s   CODES_VERIFIED: %s  (must stay False)'
      % (sorted(es.TRAVEL_CODES), es.CODES_VERIFIED))

# Every Observation-based section must attribute to exactly ONE section.
rng = random.Random(7)
samples = [('vital sign', opt._vital_signs('Patient/p','1970-05-05',rng)[0]),
           ('social history', opt._social_history('Patient/p','1970-05-05',rng)[0]),
           ('functional status', opt._functional_status('Patient/p','1970-05-05',rng)[0]),
           ('travel', eu._travel_history('Patient/p',rng)[0]),
           ('patient-provided', eu._patient_provided('Patient/p',rng)[0])]
for _ in range(80):
    pr = opt._pregnancy('Patient/p','1990-05-05','female',rng)
    if pr: samples.append(('pregnancy', pr[0])); break
print('  each Observation kind -> its section:')
bad = 0
for label, body in samples:
    present = [k for k,v in es.status_for_resources([R(body['resourceType'], body)]).items() if v=='PRESENT']
    if len(present) != 1: bad += 1
    print('    %-18s %s' % (label, present))
print('  kinds matching more than one section: %d  (must be 0)' % bad)

# The MDR invariant.
rng2 = random.Random(3)
flags = untagged = 0
for _ in range(400):
    for b in eu.eu_addition_sections_for('Patient/p', rng=rng2):
        if b['resourceType'] == 'Flag':
            flags += 1
            if not eu.is_simulated(b): untagged += 1
print('  Flags generated: %d, WITHOUT the simulated tag: %d  (must be 0)' % (flags, untagged))
print('  is_simulated on an untagged Flag: %s  (must be False -- a computed'
      % eu.is_simulated({'resourceType':'Flag'}))
print('    alert must not be mistaken for test data either)')
"
echo
echo "Done. Backup: $BACKUP"
echo "Roll back: cp -rp $BACKUP/app $LIVE/app && (cd $LIVE && $DC up -d --build app)"
