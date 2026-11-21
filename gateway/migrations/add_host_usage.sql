-- #1017 (eps rename phase 2, epic #1015): per-(Host, caller) request counter.
--
-- A NEW TABLE, so `db.create_all()` creates it on app start (the gunicorn
-- workers race for it and the loser logs and skips, app/__init__.py). This
-- file is the same thing, explicit and idempotent, for an operator who wants
-- the table to exist before the new code serves its first request.
--
-- Additive only: no existing table, column or row is touched. Rows hold no
-- secret: a key's row guid and label, a read-grant partner guid, an SSO
-- user_type, a refused credential's scheme, or a User-Agent product token.
--
-- Read it with `flask host-usage [--host ips.pdhc.se]` inside ips-app-1.
--
-- Run on miserver:
--   docker exec -i ips-db-1 psql -U ips_user -d ips_db -f - < add_host_usage.sql

CREATE TABLE IF NOT EXISTS host_usage (
    host          VARCHAR(255) NOT NULL,
    caller_kind   VARCHAR(32)  NOT NULL,
    caller_id     VARCHAR(128) NOT NULL,
    caller_label  VARCHAR(255),
    count         BIGINT       NOT NULL DEFAULT 0,
    first_seen    TIMESTAMPTZ  NOT NULL,
    last_seen     TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (host, caller_kind, caller_id)
);
