"""#1017 — eps rename phase 2: ips answers as eps.pdhc on both addresses.

Four things, one class each:

1. The SSO client pair is chosen by the host the request arrived on, with a
   fallback to the original pair while the EPS pair is not configured.
2. The service names itself eps.pdhc (health, CapabilityStatement, UI), and
   the health body keeps the old name as an alias.
3. This service's own IPS_<NAME> environment variables are read as
   EPS_<NAME> first, IPS_<NAME> as fallback; both empty = unset.
4. API requests are counted per (Host, caller), never storing a secret.
"""
from __future__ import annotations

import importlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.api import external_read_routes as er
from app.api import sso_routes
from app.models.api_key import ApiKey
from app.models.host_usage import HostUsage
from app.services import auth_service
from app.services.auth_service import hash_api_key

EPS = "https://eps.pdhc.se"
IPS = "https://ips.pdhc.se"

OLD_PAIR = {"SSO_CLIENT_ID": "old-id", "SSO_CLIENT_SECRET": "old-secret"}
EPS_PAIR = {"SSO_CLIENT_ID_EPS": "eps-id", "SSO_CLIENT_SECRET_EPS": "eps-secret"}
NO_EPS = {"SSO_CLIENT_ID_EPS": "", "SSO_CLIENT_SECRET_EPS": ""}


def _ok(body=None):
    r = MagicMock(status_code=200)
    r.json.return_value = body or {"email": "a@b.se", "user_type": "professional"}
    return r


# ---------------------------------------------------------------------------
# 1. SSO pair by host
# ---------------------------------------------------------------------------

class TestSsoPairByHost:
    def _callback(self, client, base_url, cfg):
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append(dict(headers or {}))
            return _ok()

        with client.session_transaction(base_url=base_url) as s:
            s["sso_state"] = "st"
        with patch.dict(client.application.config,
                        {"OAUTH_BASE_URL": "http://sso", **cfg}), \
                patch.object(sso_routes.httpx, "get", side_effect=fake_get):
            resp = client.get("/callback?state=st&token=tok", base_url=base_url)
        assert resp.status_code == 302, resp.data
        assert len(seen) == 1
        return seen[0]

    def test_eps_host_uses_the_eps_pair(self, client):
        h = self._callback(client, EPS, {**OLD_PAIR, **EPS_PAIR})
        assert h["X-SSO-Client-Id"] == "eps-id"
        assert h["X-SSO-Client-Secret"] == "eps-secret"

    def test_eps_host_falls_back_when_eps_pair_unset(self, client):
        h = self._callback(client, EPS, {**OLD_PAIR, **NO_EPS})
        assert h["X-SSO-Client-Id"] == "old-id"
        assert h["X-SSO-Client-Secret"] == "old-secret"

    def test_half_an_eps_pair_is_not_used(self, client):
        h = self._callback(client, EPS, {**OLD_PAIR, "SSO_CLIENT_ID_EPS": "eps-id",
                                         "SSO_CLIENT_SECRET_EPS": ""})
        assert h["X-SSO-Client-Id"] == "old-id"

    def test_ips_host_keeps_the_old_pair_even_when_eps_is_set(self, client):
        h = self._callback(client, IPS, {**OLD_PAIR, **EPS_PAIR})
        assert h["X-SSO-Client-Id"] == "old-id"

    def test_forwarded_host_selects_the_pair(self, client):
        """nginx -> container: the Host arrives as X-Forwarded-Host
        (ProxyFix x_host=1)."""
        seen = []
        with client.session_transaction(base_url="http://127.0.0.1:9040") as s:
            s["sso_state"] = "st"
        with patch.dict(client.application.config,
                        {"OAUTH_BASE_URL": "http://sso", **OLD_PAIR, **EPS_PAIR}), \
                patch.object(sso_routes.httpx, "get",
                             side_effect=lambda u, headers=None, timeout=None:
                             (seen.append(headers), _ok())[1]):
            client.get("/callback?state=st&token=tok",
                       base_url="http://127.0.0.1:9040",
                       headers={"X-Forwarded-Host": "eps.pdhc.se",
                                "X-Forwarded-Proto": "https",
                                "X-Forwarded-For": "10.0.0.1"})
        assert seen and seen[0]["X-SSO-Client-Id"] == "eps-id"

    @pytest.mark.parametrize("base", [EPS, IPS])
    def test_login_callback_uri_uses_the_arrival_host(self, client, base):
        resp = client.get("/login", base_url=base)
        loc = resp.headers["Location"]
        assert f"next={base}/callback&" in loc

    def test_bearer_validation_uses_the_host_pair(self, app):
        seen = []
        with patch.dict(app.config, {"OAUTH_BASE_URL": "http://sso",
                                     **OLD_PAIR, **EPS_PAIR}), \
                patch.object(auth_service.httpx, "get",
                             side_effect=lambda u, headers=None, timeout=None:
                             (seen.append(headers), _ok())[1]):
            with app.test_request_context("/api/v1/x", base_url=EPS):
                auth_service.resolve_sso_user("t")
            with app.test_request_context("/api/v1/x", base_url=IPS):
                auth_service.resolve_sso_user("t")
        assert [h["X-SSO-Client-Id"] for h in seen] == ["eps-id", "old-id"]

    def test_external_read_gate_uses_the_host_pair(self, client):
        seen = []

        def post(url, json=None, headers=None, timeout=None):
            seen.append(headers)
            r = MagicMock(status_code=401)
            r.json.return_value = {}
            return r

        with patch.dict(client.application.config,
                        {"OAUTH_BASE_URL": "http://sso", **OLD_PAIR, **EPS_PAIR}), \
                patch.object(er.httpx, "post", side_effect=post):
            client.get("/external/v1/patients", base_url=EPS,
                       headers={"Authorization": "Bearer rg.x.y"})
        assert seen and seen[0]["X-SSO-Client-Id"] == "eps-id"


# ---------------------------------------------------------------------------
# 2. The service's own name
# ---------------------------------------------------------------------------

class TestServiceName:
    def test_health_names_eps_and_keeps_the_old_name_as_alias(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["service"] == "eps.pdhc"
        assert "ips-server" in data["service_aliases"]

    def test_capability_statement_names_eps(self, client):
        cs = client.get("/fhir/metadata").get_json()
        assert cs["title"].startswith("eps.pdhc")
        assert cs["name"] == "EpsPDHCCapabilityStatement"
        assert cs["implementation"]["description"] == "eps.pdhc production instance"
        assert "ips.pdhc.se" not in cs["url"]

    def test_ui_title_and_brand_name_eps(self, client):
        html = client.get("/admin/").data
        assert b"<title>Dashboard \xe2\x80\x94 PDHC eps.pdhc</title>" in html
        assert b">eps.pdhc</a>" in html
        assert b"IPS Server" not in html

    def test_log_lines_carry_the_service_name(self):
        """Under pytest the root logger already has handlers, so
        basicConfig is a no-op here; assert what create_app ASKS for."""
        from app import create_app
        with patch("logging.basicConfig") as bc:
            create_app("testing")
        assert "eps.pdhc" in bc.call_args.kwargs["format"]


# ---------------------------------------------------------------------------
# 3. EPS_* first, IPS_* fallback
# ---------------------------------------------------------------------------

NAMES = ["WEBHOOK_SECRET", "WEBHOOK_TARGETS", "WEBHOOK_TIMEOUT",
         "INDISPENSABLE_LIFT_ROLES", "EMERGENCY_ACCESS_ROLES",
         "ADMIN_REQUIRE_ANALYSIS_PHASE"]


@pytest.fixture
def clean_env(monkeypatch):
    for n in NAMES:
        monkeypatch.delenv("EPS_" + n, raising=False)
        monkeypatch.delenv("IPS_" + n, raising=False)
    return monkeypatch


def _fresh_config():
    import app.config as cfg
    return importlib.reload(cfg).Config


class TestEnvNames:
    def test_helper_order(self, clean_env):
        from app.services.env_names import env_value
        assert env_value("WEBHOOK_SECRET", "d") == "d"
        clean_env.setenv("IPS_WEBHOOK_SECRET", "old")
        assert env_value("WEBHOOK_SECRET") == "old"
        clean_env.setenv("EPS_WEBHOOK_SECRET", "new")
        assert env_value("WEBHOOK_SECRET") == "new"
        clean_env.setenv("EPS_WEBHOOK_SECRET", "")
        assert env_value("WEBHOOK_SECRET") == "old"  # empty EPS never masks IPS
        clean_env.setenv("IPS_WEBHOOK_SECRET", "")
        assert env_value("WEBHOOK_SECRET") is None

    def test_config_reads_eps_first(self, clean_env):
        try:
            clean_env.setenv("IPS_WEBHOOK_SECRET", "old")
            clean_env.setenv("EPS_WEBHOOK_SECRET", "new")
            clean_env.setenv("EPS_WEBHOOK_TARGETS", "http://a, http://b")
            clean_env.setenv("IPS_WEBHOOK_TIMEOUT", "9")
            C = _fresh_config()
            assert C.IPS_WEBHOOK_SECRET == "new"
            assert C.IPS_WEBHOOK_TARGETS == ["http://a", "http://b"]
            assert C.IPS_WEBHOOK_TIMEOUT == 9.0
        finally:
            clean_env.undo()
            _fresh_config()

    def test_config_defaults_unchanged_when_both_unset(self, clean_env):
        try:
            C = _fresh_config()
            assert C.IPS_WEBHOOK_SECRET == ""
            assert C.IPS_WEBHOOK_TARGETS == []
            assert C.IPS_WEBHOOK_TIMEOUT == 5.0
            assert C.IPS_ADMIN_REQUIRE_ANALYSIS_PHASE is False
            assert C.SSO_CLIENT_ID_EPS == "" and C.SSO_CLIENT_SECRET_EPS == ""
        finally:
            clean_env.undo()
            _fresh_config()

    @pytest.mark.parametrize("val,expected", [
        ("true", True), ("1", True), ("on", True),
        ("false", False), ("0", False), ("", False)])
    def test_phase_flag_reaches_config(self, clean_env, val, expected):
        try:
            clean_env.setenv("EPS_ADMIN_REQUIRE_ANALYSIS_PHASE", val)
            assert _fresh_config().IPS_ADMIN_REQUIRE_ANALYSIS_PHASE is expected
        finally:
            clean_env.undo()
            _fresh_config()

    def test_role_gates_read_eps_first(self, app, clean_env):
        from app import admin_block_lift
        from app.api import admin_blocks_routes, care_access_routes
        clean_env.setenv("IPS_INDISPENSABLE_LIFT_ROLES", "nurse")
        clean_env.setenv("EPS_INDISPENSABLE_LIFT_ROLES", "surgeon")
        clean_env.setenv("IPS_EMERGENCY_ACCESS_ROLES", "x")
        clean_env.setenv("EPS_EMERGENCY_ACCESS_ROLES", "medic")
        with patch.dict(app.config, {"IPS_INDISPENSABLE_LIFT_ROLES": None,
                                     "IPS_EMERGENCY_ACCESS_ROLES": None}):
            with app.app_context():
                assert admin_block_lift._allowed_lift_roles() == {"surgeon"}
                assert admin_blocks_routes._allowed_roles() == {"surgeon"}
                assert care_access_routes._allowed_roles() == {"medic"}
                clean_env.delenv("EPS_INDISPENSABLE_LIFT_ROLES")
                assert admin_block_lift._allowed_lift_roles() == {"nurse"}
                clean_env.delenv("IPS_INDISPENSABLE_LIFT_ROLES")
                assert admin_block_lift._allowed_lift_roles() == {"physician", "admin"}


# ---------------------------------------------------------------------------
# 4. Per-(host, caller) counter
# ---------------------------------------------------------------------------

def _rows(db):
    db.session.expire_all()
    return {(r.host, r.caller_kind, r.caller_id): r
            for r in db.session.query(HostUsage).all()}


class TestHostUsageCounter:
    def test_counts_per_host_and_caller(self, client, db):
        ua = {"User-Agent": "python-httpx/0.27.0"}
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            client.get("/api/v1/health", base_url=IPS, headers=ua)
            client.get("/api/v1/health", base_url=IPS, headers=ua)
            client.get("/api/v1/health", base_url=EPS, headers=ua)
        rows = _rows(db)
        assert rows[("ips.pdhc.se", "anonymous", "python-httpx")].count == 2
        assert rows[("eps.pdhc.se", "anonymous", "python-httpx")].count == 1
        r = rows[("ips.pdhc.se", "anonymous", "python-httpx")]
        assert r.last_seen >= r.first_seen

    def test_api_key_caller_is_recorded_without_the_secret(self, client, db):
        raw = f"secret-{uuid.uuid4()}"
        key = ApiKey(key_hash=hash_api_key(raw), label="cdr2.pdhc ingest",
                     prefix=raw[:8], scopes=[], is_active=True)
        db.session.add(key)
        db.session.commit()
        kid = str(key.guid)
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            resp = client.get("/fhir/Condition?patient=x", base_url=IPS,
                              headers={"Authorization": f"ApiKey {raw}"})
        assert resp.status_code == 200, resp.data
        rows = _rows(db)
        r = rows[("ips.pdhc.se", "apikey", kid)]
        assert r.count == 1 and r.caller_label == "cdr2.pdhc ingest"
        for row in rows.values():
            for v in (row.host, row.caller_kind, row.caller_id, row.caller_label or ""):
                assert raw not in v and raw[:8] not in v

    def test_refused_credential_records_scheme_only(self, client, db):
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}):
            resp = client.get("/fhir/Condition?patient=x", base_url=IPS,
                              headers={"Authorization": "ApiKey not-a-key-123"})
        assert resp.status_code == 401
        assert ("ips.pdhc.se", "rejected", "ApiKey") in _rows(db)

    def test_bearer_records_user_type(self, client, db):
        with patch.dict(client.application.config, {"AUTH_DISABLED": False}), \
                patch.object(auth_service, "resolve_sso_user",
                             return_value={"user_type": "patient",
                                           "patient_guid": str(uuid.uuid4())}):
            client.get("/api/v1/patient/blocks", base_url=EPS,
                       headers={"Authorization": "Bearer tok"})
        assert ("eps.pdhc.se", "bearer", "patient") in _rows(db)

    def test_non_api_paths_are_not_counted(self, client, db):
        client.get("/admin/", base_url=IPS)
        client.get("/login", base_url=IPS)
        assert _rows(db) == {}

    def test_a_failing_counter_never_breaks_the_request(self, client, db):
        from app.services import host_usage as hu
        with patch.object(hu, "caller_identity", side_effect=RuntimeError("x")):
            resp = client.get("/api/v1/health", base_url=IPS)
        assert resp.status_code == 200

    def test_cli_lists_rows_read_only(self, app, client, db):
        with patch.dict(app.config, {"AUTH_DISABLED": False}):
            client.get("/api/v1/health", base_url=IPS,
                       headers={"User-Agent": "curl/8.4"})
            client.get("/api/v1/health", base_url=EPS,
                       headers={"User-Agent": "curl/8.4"})
        before = {k: v.count for k, v in _rows(db).items()}
        out = app.test_cli_runner().invoke(args=["host-usage", "--host", "ips.pdhc.se"])
        assert out.exit_code == 0, out.output
        assert "ips.pdhc.se\tanonymous\tcurl\t" in out.output  # product token only
        assert "eps.pdhc.se" not in out.output
        assert "1 row(s), 1 request(s)" in out.output
        assert {k: v.count for k, v in _rows(db).items()} == before
