#!/usr/bin/env bash
# ============================================================
# IPS — start.sh
# Docker DB + gunicorn app. Docker must already be running.
# IMPORTANT: Do NOT kill -9 on Docker-forwarded ports (9041).
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

log()  { echo -e "\033[0;32m[IPS]\033[0m $1"; }
warn() { echo -e "\033[1;33m[IPS]\033[0m $1"; }
err()  { echo -e "\033[0;31m[IPS]\033[0m $1"; }

# ── 1. Docker check ──────────────────────────────────────────
log "=== IPS starting ==="

if ! docker info >/dev/null 2>&1; then
    err "Docker is not running."
    err "  Run: bash /usr/local/www/restart_all.sh"
    exit 1
fi
log "Docker OK"

# ── 2. Stop existing ─────────────────────────────────────────
# Stop gunicorn first (port 9040 — host process, safe to kill)
if [ -f "$SCRIPT_DIR/gunicorn.pid" ]; then
    kill "$(cat "$SCRIPT_DIR/gunicorn.pid")" 2>/dev/null || true
    rm -f "$SCRIPT_DIR/gunicorn.pid"
    log "Stopped gunicorn"
fi

# Stop Docker containers (releases port 9041 safely)
log "Stopping existing containers..."
docker-compose down 2>/dev/null || true

# ── 3. Start DB ──────────────────────────────────────────────
log "Starting PostgreSQL..."
docker-compose up -d db

if [ $? -ne 0 ]; then
    err "Failed to start DB container."
    exit 1
fi

log "Waiting for DB..."
for i in $(seq 1 30); do
    if docker-compose exec -T db pg_isready -U "${POSTGRES_USER:-ips_user}" >/dev/null 2>&1; then
        log "Database ready."
        break
    fi
    [ "$i" -eq 30 ] && err "DB not ready after 30s"
    sleep 1
done

# ── 4. Virtual environment ───────────────────────────────────
if [ ! -d "venv" ]; then
    log "Creating virtual environment..."
    python3 -m venv venv
fi
log "Activating venv..."
source venv/bin/activate
pip install -q -r requirements.txt

# ── 5. Load .env ─────────────────────────────────────────────
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# ── 6. Start gunicorn ────────────────────────────────────────
log "Starting gunicorn on port ${APP_PORT:-9040}..."
mkdir -p logs

nohup gunicorn \
    --bind 127.0.0.1:${APP_PORT:-9040} \
    --workers 2 \
    --timeout 120 \
    --max-requests 500 \
    --max-requests-jitter 50 \
    --access-logfile "$SCRIPT_DIR/logs/access.log" \
    --error-logfile "$SCRIPT_DIR/logs/error.log" \
    --pid "$SCRIPT_DIR/gunicorn.pid" \
    "wsgi:app" >> "$SCRIPT_DIR/logs/gunicorn.out" 2>&1 &

# ── 7. Health check ──────────────────────────────────────────
HTTP_CODE="000"
for i in $(seq 1 15); do
    sleep 1
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${APP_PORT:-9040}/api/v1/health 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ] && break
done

if [ "$HTTP_CODE" = "200" ]; then
    log "Health check: PASSED"
else
    warn "Health check: HTTP $HTTP_CODE — check $SCRIPT_DIR/logs/"
fi

log "=== IPS is running ==="
log "  App:  http://127.0.0.1:${APP_PORT:-9040}"
log "  DB:   localhost:9041"
log "  Logs: $SCRIPT_DIR/logs/"
