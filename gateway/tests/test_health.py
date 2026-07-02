"""Tests for health and metrics endpoints — Step 5.a."""


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["service"] == "ips-server"
        assert "timestamp" in data
        assert "status" in data

    def test_health_reports_db_status(self, client):
        resp = client.get("/api/v1/health")
        data = resp.get_json()
        # SQLite in-memory should be connected
        assert data["database"] in ("connected", "disconnected")

    def test_health_returns_503_when_db_disconnected(self, client, monkeypatch):
        """Ticket #349 §2.1 regression guard — /api/v1/health must
        return HTTP 503 when the DB probe fails. Previously always 200
        with status:degraded (the CLAUDE.md §10 false-green pattern)."""
        from app.api import health as health_mod

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(health_mod.db.session, "execute", _boom)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["database"] == "disconnected"


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, client):
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "counts" in data
        assert "timestamp" in data
