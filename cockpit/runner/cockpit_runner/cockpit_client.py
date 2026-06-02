from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx

from cockpit_runner.config import settings


@dataclass(slots=True)
class ClaimedRequest:
    id: UUID
    instance_slug: str
    instance_base_url: str
    instance_channel: str
    target_version: str


class CockpitClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.cockpit_url,
            timeout=settings.http_timeout_s,
            headers={"Authorization": f"Bearer {settings.cockpit_token}"},
        )

    def close(self) -> None:
        self._client.close()

    def claim_next(self) -> ClaimedRequest | None:
        r = self._client.get("/api/update-requests/next")
        r.raise_for_status()
        if r.text in ("null", ""):
            return None
        data = r.json()
        if data is None:
            return None
        return ClaimedRequest(
            id=UUID(data["id"]),
            instance_slug=data["instance_slug"],
            instance_base_url=data["instance_base_url"],
            instance_channel=data["instance_channel"],
            target_version=data["target_version"],
        )

    def complete(self, request_id: UUID) -> None:
        r = self._client.post(f"/api/update-requests/{request_id}/complete")
        r.raise_for_status()

    def fail(self, request_id: UUID, error: str) -> None:
        r = self._client.post(f"/api/update-requests/{request_id}/fail", json={"error": error})
        r.raise_for_status()
