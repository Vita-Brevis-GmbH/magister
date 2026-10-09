from fastapi.testclient import TestClient


def test_update_requests_requires_auth(client: TestClient) -> None:
    r = client.get("/api/update-requests")
    assert r.status_code == 401
