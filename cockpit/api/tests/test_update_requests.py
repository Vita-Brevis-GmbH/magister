from fastapi.testclient import TestClient

from cockpit_api.main import app


def test_update_requests_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/api/update-requests")
        assert r.status_code == 401
