from fastapi.testclient import TestClient

from cockpit_api.main import app


def test_health() -> None:
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_instances_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/api/instances")
        assert r.status_code == 401


def test_security_headers_present() -> None:
    # hardening-audit L-06: every Cockpit API response carries the baseline
    # security headers, including a locked-down CSP with frame-ancestors 'none'.
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
