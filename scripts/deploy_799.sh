#!/usr/bin/env bash
# ============================================================
# ips.pdhc — euIPS #798 + #799 (consumer contract check, completeness report).
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
# copies from git 8c2e2b6.
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
docker exec ips-app-1 sh -c 'test -f /app/app/services/euips_report.py && echo "  euips_report.py: present" || echo "  *** MISSING ***"'
docker exec ips-app-1 sh -c 'test -f /app/scripts/contract_check.py && echo "  contract_check.py: present" || echo "  *** MISSING ***"'
echo
echo "  === the consumer contract, against this running service (#798) ==="
docker exec ips-app-1 python /app/scripts/contract_check.py 2>&1 | grep -v "^20[0-9][0-9]-" | sed 's/^/  /'
echo
echo "  === the euIPS baseline over the EXISTING patients (#799) ==="
docker exec -e FLASK_APP=app ips-app-1 sh -c 'cd /app && flask euips-report' 2>&1 | grep -v "^20[0-9][0-9]-" | sed 's/^/  /'
echo
echo "Done. Backup: $BACKUP"
echo "Roll back: cp -rp $BACKUP/app $LIVE/app && (cd $LIVE && $DC up -d --build app)"
