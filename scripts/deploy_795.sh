#!/usr/bin/env bash
# ============================================================
# ips.pdhc — euIPS #795 (the seven OPTIONAL sections + the #791 discrimination fix).
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
# copies from git f0227da.
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
docker exec ips-app-1 sh -c 'test -f /app/app/services/euips_optional.py && echo "  euips_optional.py: present" || echo "  euips_optional.py: *** MISSING ***"'

# The #791 conformance bug this ticket fixed, asserted against the LIVE code.
docker exec ips-app-1 python -c "
import sys; sys.path.insert(0, '/app')
from app.services import euips_sections as es
class R:
    def __init__(s, t, j): s.resource_type, s.resource_json = t, j
vs = R('Observation', {'resourceType':'Observation',
                       'category':[{'coding':[{'code':'vital-signs'}]}],
                       'code':{'coding':[{'code':'8867-4'}]},
                       'subject':{'reference':'Patient/p'}})
st = es.status_for_resources([vs])
print('  one vital-sign Observation marks PRESENT: %s' % [k for k,v in st.items() if v=='PRESENT'])
res = R('Condition', {'resourceType':'Condition',
                      'clinicalStatus':{'coding':[{'code':'resolved'}]},
                      'code':{'coding':[{'code':'233604007'}]}})
st2 = es.status_for_resources([res])
print('  one RESOLVED Condition: problems=%s past_illnesses=%s conformant=%s'
      % (st2['problems'], st2['past_illnesses'], es.is_conformant(st2)))
print('    (was problems=PRESENT and conformant=True -- an empty active problem list)')
shared = {}
for sec in es.SECTIONS:
    for t in sec.resource_types:
        shared.setdefault(t, []).append(sec)
bad = [s.key for t, secs in shared.items() if len(secs) > 1 for s in secs if not s.discriminator]
print('  sections sharing a type with no discriminator: %s' % (bad or 'none'))
"
echo
docker exec ips-app-1 python -c "
import sys, random; sys.path.insert(0, '/app')
from collections import Counter
from app.services import euips_optional as opt, euips_sections as es
class R:
    def __init__(s, t, j): s.resource_type, s.resource_json = t, j
rng = random.Random(8)
keys = ('vital_signs','past_illnesses','pregnancy','social_history',
        'functional_status','plan_of_care','advance_directives')
c = {k: 0 for k in keys}
male_pregnancy = child_pregnancy = old_current = no_category = 0
N = 250
for _ in range(N):
    g = rng.choice(['male','female'])
    birth = '%d-05-05' % rng.randint(1935, 2015)
    bodies = opt.optional_sections_for('Patient/p', birth, g, rng=rng)
    st = es.status_for_resources([R(b['resourceType'], b) for b in bodies])
    for k in keys:
        if st[k] == 'PRESENT': c[k] += 1
    for b in bodies:
        codes = {x.get('code') for x in (b.get('code') or {}).get('coding') or []}
        preg = bool(codes & es.PREGNANCY_CODES)
        if preg and g == 'male': male_pregnancy += 1
        if preg and int(birth[:4]) > 2010: child_pregnancy += 1
        if '82810-3' in codes and int(birth[:4]) < 1970: old_current += 1
        if b['resourceType'] == 'Observation' and not b.get('category'): no_category += 1
print('  live code over %d patients, sections PRESENT:' % N)
for k in keys: print('    %-20s %3d' % (k, c[k]))
print('  pregnancy on a male patient        : %d  (must be 0)' % male_pregnancy)
print('  pregnancy on a child               : %d  (must be 0)' % child_pregnancy)
print('  CURRENT pregnancy over the age bound: %d  (must be 0)' % old_current)
print('  Observations with no category      : %d  (must be 0)' % no_category)
"
echo
echo "  _mock_patient_resources is gone:"
docker exec ips-app-1 sh -c 'grep -c "^def _mock_patient_resources" /app/app/admin.py || true' | sed 's/^/    definitions (want 0): /'
echo
echo "Done. Backup: $BACKUP"
echo "Roll back: cp -rp $BACKUP/app $LIVE/app && (cd $LIVE && $DC up -d --build app)"
