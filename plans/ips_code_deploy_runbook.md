# ips.pdhc code deploy — prepared AND EXECUTED 2026-11-02

> **DEPLOYED 2026-11-02T17:13Z and verified.** Rollback artifact:
> `~/backups/predeploy/ips.pdhc/gateway_2026-11-02T17-11-32Z.tgz`
> (27.6 MB, 3722 entries). What happened is in `progress.md`.

The three EPS migrations are live; the code that uses them is not. This is
what deploying it needs, with every risk measured rather than assumed.

**Operator-gated.** Platform CLAUDE.md §15.

---

## What was verified before writing this

| check | result |
|---|---|
| **Where production actually is** | `/usr/local/www/pdhcips/gateway` — **not** `/usr/local/www/ips.pdhc/`. A plain directory: no `current`, no `releases/`, no `shared/`, not a git checkout |
| **Server-only edits** | **NONE.** All 24 changed files match a committed git version (2026-03-23 to 2026-10-23). The server is behind, not divergent |
| **Files on the server but not local** | none — nothing would be orphaned |
| **The #858 bind trap** | closed. Server Dockerfile already `--bind 0.0.0.0:9040`, local the same, no compose `command:` override, host mapping `127.0.0.1:9040:9040` is the confinement |
| **Dependency drift on `--build`** | not a risk here. All **13** requirements are pinned with `==`, so a rebuild installs the same versions (#785 does not apply to ips) |
| **New env vars required** | none. Five keys are referenced and absent from `.env`, all pre-existing and all read with `.get()` and a fallback — verified no `config[...]` access |

### The check that nearly gave a false alarm

The divergence test first reported **all 24 files as server-only edits**. That
was wrong, and the cause is a zsh trap worth writing down:

```zsh
git show "$C:gateway/app/foo.py"     # WRONG — zsh eats `:ga` as a modifier
git show "${C}:gateway/app/foo.py"   # right
```

`:a` is zsh's "make absolute path" parameter modifier, so `$C:ga…` expanded to
the CWD prepended to a mangled path. `git show` then returned nothing, and
every file hashed as the empty string — `e3b0c44298fc1c14`, which is sha256 of
"". Believing that output would have stopped a correct deploy.

---

## The deploy

### 1. Rollback artifact first — there is no symlink to flip

```bash
ssh miserver 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; \
  mkdir -p ~/backups/predeploy/ips.pdhc && \
  cd /usr/local/www/pdhcips && \
  tar czf ~/backups/predeploy/ips.pdhc/gateway_$(date -u +%Y-%m-%dT%H-%M-%SZ).tgz gateway'
```

Verify it is non-empty and lists `gateway/app/__init__.py` before continuing.
This is the ONLY rollback path: the directory has no release layout, so
reverting means extracting this tarball and rebuilding.

### 2. Copy the source

34 files: 24 changed + 10 new, under `app/` and `migrations/`, plus
`Dockerfile`. Copy `app/` and `migrations/` wholesale — nothing on the server
is unique, so there is nothing to preserve.

**Do NOT copy `.env`** (server-owned, and the local one is dev) **or
`docker-compose.yml`** (the server's has its own port and env wiring).

### 3. Rebuild — `--build` is mandatory

The Dockerfile does `COPY . .`, so `docker compose up -d` WITHOUT `--build`
would start the OLD image and the copy would have no effect
(`infra_docker_copy_dot_needs_build_flag`).

```bash
cd /usr/local/www/pdhcips/gateway && docker-compose up -d --build app
```

**`docker-compose`, with the hyphen.** Probed on the box 2026-11-02:
`docker compose` (the v2 plugin) is **absent** and only `docker-compose` 5.1.4
exists. The hyphenless form in the first draft of this runbook would have
failed — CLAUDE.md §8 point 3 says to probe and fall back, and this is why.

### 4. Verify the code actually landed

A green healthcheck does not prove the new code is running — the container has
been ahead of, and behind, its directory before.

```bash
docker exec ips-app-1 grep -c patient_proxy_grant app/models/patient_proxy_grant.py
docker exec ips-app-1 grep -c admin_access_policy app/admin.py
curl -s https://ips.pdhc.se/api/v1/health
```

### 5. Build the projection

`patient_state_facts` is empty: the migration created it, nothing fills it.

```bash
docker exec ips-app-1 flask rebuild-patient-state
```

Safe at any time — every row is derived, and the command deletes and
re-derives rather than patching.

---

## WHAT CHANGES BEHAVIOUR THE MOMENT THIS DEPLOYS

Read this before step 3, not after.

1. **The #902 admin gate becomes active.** `/admin/*` currently admits anyone
   with an SSO session — including a patient. After this deploy it requires
   professional-or-SU. **If anyone uses the ips admin UI with a non-professional
   account, they lose access.** The `"analysis"` phase half stays
   SHADOW-LOGGED (`IPS_ADMIN_REQUIRE_ANALYSIS_PHASE` unset), so that half
   refuses nobody and writes a WARNING naming who it would refuse. Flip the
   flag later, once the log is quiet.

2. **Three authorisation paths narrow to ACTIVE assignments** (#899b: spärr,
   consent, care access). No row has `ended_at`, so this changes no real answer
   today — which is why it was done now rather than after the first assignment
   ends.

3. **New routes appear**: the patient proxy surface (#889), the implant
   transport (#903, scoped to an API key nobody holds yet), the patient-state
   read route (#895) and the export (#896).

4. **`/register-patient`-style enrolment is unaffected** — that is sso, not ips.

---

## Rollback

```bash
cd /usr/local/www/pdhcips && rm -rf gateway && \
  tar xzf ~/backups/predeploy/ips.pdhc/gateway_2026-11-02T17-11-32Z.tgz && \
  cd gateway && docker-compose up -d --build app
```

The database migrations are NOT rolled back by this, and do not need to be:
they are additive plus one constraint swap, and the old code neither reads nor
writes any of it — measured, `grep` inside the running container found 0 files
mentioning `patient_state_facts`, `patient_proxy_grants` or `ended_at`.
