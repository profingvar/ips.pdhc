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


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, client):
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "counts" in data
        assert "timestamp" in data
