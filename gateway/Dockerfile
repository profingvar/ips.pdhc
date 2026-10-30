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

# Bind to 0.0.0.0 — inside a container this is NOT the same decision as on
# bare metal. The loopback interface here is the CONTAINER's own, so binding
# it does not narrow exposure; it removes reachability altogether. Docker
# forwards a published port over the bridge, never over the container's
# loopback, so `--bind 127.0.0.1` leaves the host mapping dead while the
# HEALTHCHECK above — which curls from INSIDE, where it works — keeps
# reporting the container healthy. A `--build` redeploy from this file would
# therefore take ips.pdhc.se down with `docker ps` green throughout.
#
# The control that confines ips is the host-side mapping prefix in
# docker-compose.yml:29, `127.0.0.1:9040:9040`. That line, not this bind, is
# what keeps the service off the LAN — keep it.
#
# The previous comment cited #349 §1.1 and worried about someone running the
# image by hand with a bare `-p 9040:9040`. The concern was real but the
# control sat in the wrong layer: such a person has already bypassed the
# compose file, and the bind never mitigated it. Changed by #858. Production
# has run `--bind 0.0.0.0:9040` all along, so this file was the divergence.
#
# --access-logfile - flows HTTP access lines to `docker logs`, #349 §1.2.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:9040", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--access-logformat", "%(t)s %(h)s \"%(r)s\" %(s)s %(L)ss", \
     "wsgi:app"]
