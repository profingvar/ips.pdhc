#!/usr/bin/env bash
# IPS Server — Single start script (Rule 16)
# Kills ports 9040-9043, starts Docker DB, activates venv, starts Flask.
# Ctrl+C gracefully shuts down everything.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[IPS]${NC} $1"; }
warn() { echo -e "${YELLOW}[IPS]${NC} $1"; }
err() { echo -e "${RED}[IPS]${NC} $1"; }

# ── Cleanup function ────────────────────────────────────────
cleanup() {
    log "Shutting down..."
    # Stop Flask (if running in background)
    if [ -n "$FLASK_PID" ] && kill -0 "$FLASK_PID" 2>/dev/null; then
        kill "$FLASK_PID" 2>/dev/null || true
        wait "$FLASK_PID" 2>/dev/null || true
    fi
    # Stop Docker containers
    if command -v docker-compose &>/dev/null; then
        docker-compose down 2>/dev/null || true
    elif docker compose version &>/dev/null 2>&1; then
        docker compose down 2>/dev/null || true
    fi
    # Deactivate venv
    if [ -n "$VIRTUAL_ENV" ]; then
        deactivate 2>/dev/null || true
    fi
    log "Shutdown complete."
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── 1. Kill processes on ports 9040-9043 ────────────────────
log "Killing any processes on ports 9040-9043..."
for port in 9040 9041 9042 9043; do
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        warn "Killing PIDs on port $port: $pids"
        echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
done

# ── 2. Ensure Docker is running ─────────────────────────────
log "Checking Docker..."
if ! docker info &>/dev/null; then
    err "Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi
log "Docker is running."

# ── 3. Start database via Docker Compose ────────────────────
log "Starting PostgreSQL database..."
if command -v docker-compose &>/dev/null; then
    docker-compose up -d db
else
    docker compose up -d db
fi

# Wait for DB to be healthy
log "Waiting for database to be ready..."
for i in $(seq 1 30); do
    if docker-compose exec -T db pg_isready -U "${POSTGRES_USER:-ips_user}" &>/dev/null 2>&1; then
        log "Database is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        err "Database did not become ready in 30 seconds."
        exit 1
    fi
    sleep 1
done

# ── 4. Activate virtual environment ─────────────────────────
if [ ! -d "venv" ]; then
    log "Creating virtual environment..."
    python3 -m venv venv
fi

log "Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
log "Installing dependencies..."
pip install -q -r requirements.txt

# ── 5. Copy .env if not present ─────────────────────────────
if [ ! -f ".env" ]; then
    warn "No .env file found. Copying from .env.example..."
    cp .env.example .env
    warn "Please edit .env with your credentials before production use."
fi

# Source .env for this script
set -a
source .env
set +a

# ── 6. Run database migrations ──────────────────────────────
log "Running database migrations..."
export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER:-ips_user}:${POSTGRES_PASSWORD:-dev}@localhost:9041/${POSTGRES_DB:-ips_db}"
# For first run, create_all handles table creation; Alembic for subsequent migrations
# alembic upgrade head 2>/dev/null || true

# ── 7. Start Flask application ──────────────────────────────
log "Starting IPS Server on port ${APP_PORT:-9040}..."
log "Admin UI available at http://localhost:${APP_PORT:-9040}/admin/"
log "FHIR endpoint at http://localhost:${APP_PORT:-9040}/fhir/metadata"
log "Health check at http://localhost:${APP_PORT:-9040}/api/v1/health"
log ""
log "Press Ctrl+C to stop."

python wsgi.py
