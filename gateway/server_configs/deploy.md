# IPS Server — Upgrade Instructions for Mac Mini

Upgrading the existing deployment at `/usr/local/www/pdhcips`.
All server commands are run by the operator.

---

## Phase 1 — Done (packaging on dev Mac)

Tarball ready at: `/Users/martiningvar/T7_sidewinder/ips.pdhc.tar.gz` (68 KB)

Copy to server:

```bash
scp /Users/martiningvar/T7_sidewinder/ips.pdhc.tar.gz miserver@192.168.1.154:/tmp/
```

---

## Phase 2 — Server: Back up old version, then unpack

```bash
ssh miserver@192.168.1.154

# 1. Check what's running on the old install
ls /usr/local/www/pdhcips/
cd /usr/local/www/pdhcips/gateway 2>/dev/null && docker-compose ps 2>/dev/null || echo "No docker-compose running"

# 2. Back up the old .env (if it exists — contains production secrets)
cp /usr/local/www/pdhcips/gateway/.env /tmp/pdhcips_env_backup 2>/dev/null || echo "No old .env"

# 3. Stop old containers (if running)
cd /usr/local/www/pdhcips/gateway 2>/dev/null && docker-compose down 2>/dev/null || true

# 4. Back up old app directory
sudo mv /usr/local/www/pdhcips /usr/local/www/pdhcips.bak-$(date +%Y%m%d)

# 5. Extract new version (tarball has ips.pdhc/ — rename to pdhcips)
cd /tmp
tar xzf ips.pdhc.tar.gz
sudo mv ips.pdhc /usr/local/www/pdhcips
sudo chown -R miserver:staff /usr/local/www/pdhcips
```

---

## Phase 3 — Server: Configure .env

```bash
cd /usr/local/www/pdhcips/gateway
cp .env.example .env

# If old .env had production values, copy them over:
cat /tmp/pdhcips_env_backup
# Then edit .env with those values:
nano .env
```

If this is a fresh `.env`, generate secrets and set:

| Variable | Action |
|----------|--------|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `POSTGRES_PASSWORD` | `python3 -c "import secrets; print(secrets.token_hex(16))"` |
| `API_KEY_SECRET` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `BOOTSTRAP_SU_USERNAME` | `admin` |
| `BOOTSTRAP_SU_PASSWORD` | Strong password (remove after first login) |
| `AUTH_DISABLED` | `false` |
| `CORS_ORIGINS` | `https://ips.pdhc.se` |
| `OAUTH_BASE_URL` | `https://sso.pdhc.se` |

```bash
# Clean up
rm /tmp/ips.pdhc.tar.gz
```

---

## Phase 4 — Server: Start Docker

```bash
cd /usr/local/www/pdhcips/gateway

# Use hyphenated docker-compose (Mac Mini convention)
docker-compose up -d

# Verify both containers are healthy
docker-compose ps

# Test locally
curl -s http://localhost:9040/api/v1/health
curl -s http://localhost:9040/fhir/metadata | head -5
curl -s -o /dev/null -w '%{http_code}' http://localhost:9040/admin/
```

---

## Phase 5 — Server: Update nginx config

The old nginx config `pdhcips.conf` is already in sites-enabled. Check what it proxies to:

```bash
cat /opt/homebrew/etc/nginx/sites-enabled/pdhcips.conf
```

**Option A — If old config already proxies to port 9040:**
No nginx changes needed. Just reload:

```bash
sudo nginx -t
sudo nginx -s reload
```

**Option B — If old config uses a different port or needs updating:**

```bash
# Back up old config
sudo cp /opt/homebrew/etc/nginx/sites-available/pdhcips.conf \
  /opt/homebrew/etc/nginx/sites-available/pdhcips.conf.bak-$(date +%Y%m%d-%H%M%S)

# Replace with new config
sudo cp /usr/local/www/pdhcips/gateway/server_configs/ips.pdhc.se.conf \
  /opt/homebrew/etc/nginx/sites-available/pdhcips.conf

# Create ACME directory (if not exists)
mkdir -p /usr/local/www/pdhcips/gateway/acme/.well-known/acme-challenge

# Test and reload
sudo nginx -t
sudo nginx -s reload
```

**SSL certificate** — if not already provisioned for ips.pdhc.se:

```bash
sudo certbot certonly --webroot \
  -w /usr/local/www/pdhcips/gateway/acme \
  -d ips.pdhc.se

sudo nginx -s reload
```

---

## Phase 6 — Verify

```bash
# Health check via HTTPS
curl -s https://ips.pdhc.se/api/v1/health

# FHIR metadata
curl -s https://ips.pdhc.se/fhir/metadata | python3 -m json.tool | head -20

# Admin dashboard
curl -s -o /dev/null -w '%{http_code}' https://ips.pdhc.se/admin/

# Documentation
curl -s -o /dev/null -w '%{http_code}' https://ips.pdhc.se/admin/docs
```

---

## Phase 7 — Clean up

After confirming everything works:

```bash
# Remove bootstrap password from .env
cd /usr/local/www/pdhcips/gateway
nano .env   # Delete BOOTSTRAP_SU_PASSWORD line
docker-compose up -d --force-recreate

# Remove old backup (only when confident)
sudo rm -rf /usr/local/www/pdhcips.bak-*

# Remove env backup
rm /tmp/pdhcips_env_backup
```

---

## Port allocation

| Project | App Port | DB Port | Subdomain |
|---------|----------|---------|-----------|
| plan.pdhc | 9030 | 9031 | plan.pdhc.se |
| forms.pdhc | 9036 | 9037 | forms.pdhc.se |
| **pdhcips** | **9040** | **9041** | **ips.pdhc.se** |

---

## Rollback (if needed)

```bash
cd /usr/local/www/pdhcips/gateway && docker-compose down
sudo mv /usr/local/www/pdhcips /usr/local/www/pdhcips.failed
sudo mv /usr/local/www/pdhcips.bak-* /usr/local/www/pdhcips
cd /usr/local/www/pdhcips/gateway && docker-compose up -d
sudo nginx -s reload
```
