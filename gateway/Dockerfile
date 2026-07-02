FROM python:3.12-slim

WORKDIR /app

# Install system deps (curl is needed for the HEALTHCHECK below)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

EXPOSE 9040

# Container-level liveness. Docker (and orchestrators that read Docker
# health) mark the container unhealthy when the app port stops answering
# for 3 consecutive polls. Ticket #349 §1.4.
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9040/api/v1/health || exit 1

# Bind to 127.0.0.1 (not 0.0.0.0). The docker-compose.yml host-side port
# mapping already restricts to 127.0.0.1, but binding on 0.0.0.0 inside
# the container is a layering violation — anyone who runs the image with
# `-p 9040:9040` (no 127.0.0.1 prefix) exposes it LAN-wide. Ticket #349
# §1.1. --access-logfile - flows HTTP access lines to `docker logs`
# per ticket #349 §1.2.
CMD ["gunicorn", \
     "--bind", "127.0.0.1:9040", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--access-logformat", "%(t)s %(h)s \"%(r)s\" %(s)s %(L)ss", \
     "wsgi:app"]
