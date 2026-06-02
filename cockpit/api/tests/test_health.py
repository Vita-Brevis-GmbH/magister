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
