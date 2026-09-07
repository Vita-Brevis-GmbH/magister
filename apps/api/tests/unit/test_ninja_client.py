"""NinjaClient: token caching + refresh, device read, script run, error mapping.

All HTTP is served by an ``httpx.MockTransport`` — no network, no real tenant.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from magister_api.ninja.client import (
    NinjaApiError,
    NinjaAuthError,
    NinjaClient,
    NinjaConfig,
    NinjaError,
    NinjaNotConfiguredError,
)


def _cfg() -> NinjaConfig:
    return NinjaConfig(region="eu", client_id="cid", client_secret="sec")


class _Handler:
    """Scriptable MockTransport handler with call bookkeeping."""

    def __init__(self) -> None:
        self.token_calls = 0
        self.paths: list[str] = []
        self.last_body: dict[str, Any] | None = None
        self.token_status = 200
        self.expires_in = 3600
        self.fail_first_device_401 = False
        self._device_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/ws/oauth/token":
            self.token_calls += 1
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{self.token_calls}",
                    "token_type": "Bearer",
                    "expires_in": self.expires_in,
                },
            )
        if request.url.path == "/v2/devices":
            after = request.url.params.get("after")
            if after is None:
                # First page: exactly _PAGE_SIZE would trigger another page; keep
                # it short so the loop terminates after one call.
                return httpx.Response(200, json=[{"id": 1, "systemName": "pc-1"}])
            return httpx.Response(200, json=[])
        if request.url.path == "/v2/device/5":
            return httpx.Response(200, json={"id": 5, "systemName": "pc-5"})
        if request.url.path == "/v2/device/9/script/run":
            self._device_calls += 1
            if self.fail_first_device_401 and self._device_calls == 1:
                return httpx.Response(401, json={"error": "expired"})
            self.last_body = json.loads(request.content.decode() or "{}")
            return httpx.Response(200, json={"jobId": 42})
        return httpx.Response(404, json={"error": "not_found"})


def _client(handler: _Handler) -> NinjaClient:
    return NinjaClient(_cfg(), transport=httpx.MockTransport(handler))


async def test_token_is_fetched_once_and_reused() -> None:
    h = _Handler()
    c = _client(h)
    try:
        await c.list_devices()
        await c.get_device(5)
    finally:
        await c.aclose()
    assert h.token_calls == 1  # cached across both calls
    assert h.paths[0] == "/ws/oauth/token"


async def test_list_devices_returns_rows() -> None:
    h = _Handler()
    c = _client(h)
    try:
        rows = await c.list_devices()
    finally:
        await c.aclose()
    assert rows == [{"id": 1, "systemName": "pc-1"}]


async def test_run_script_posts_expected_body() -> None:
    h = _Handler()
    c = _client(h)
    try:
        res = await c.run_script(9, script_id=100, parameters="--verbose", run_as="system")
    finally:
        await c.aclose()
    assert res == {"jobId": 42}
    assert h.last_body == {
        "type": "SCRIPT",
        "id": 100,
        "parameters": "--verbose",
        "runAs": "system",
    }


async def test_401_triggers_one_token_refresh_then_succeeds() -> None:
    h = _Handler()
    h.fail_first_device_401 = True
    c = _client(h)
    try:
        res = await c.run_script(9, script_id=1)
    finally:
        await c.aclose()
    assert res == {"jobId": 42}
    assert h.token_calls == 2  # initial + one forced refresh after the 401


async def test_token_rejected_raises_auth_error() -> None:
    h = _Handler()
    h.token_status = 401
    c = _client(h)
    try:
        with pytest.raises(NinjaAuthError):
            await c.list_devices()
    finally:
        await c.aclose()


async def test_api_error_carries_status_code() -> None:
    h = _Handler()
    c = _client(h)
    try:
        with pytest.raises(NinjaApiError) as ei:
            await c.get_device(999)  # handler returns 404
    finally:
        await c.aclose()
    assert ei.value.status_code == 404


def test_unknown_region_rejected() -> None:
    with pytest.raises(NinjaError):
        NinjaClient(NinjaConfig(region="mars", client_id="a", client_secret="b"))


def test_incomplete_config_rejected() -> None:
    with pytest.raises(NinjaNotConfiguredError):
        NinjaClient(NinjaConfig(region="eu", client_id="", client_secret=""))
