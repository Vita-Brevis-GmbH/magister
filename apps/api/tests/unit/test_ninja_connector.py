"""NinjaConnectorService: live match → status, re-matched script runs, guards.

No DB and no network — a real NinjaClient over an ``httpx.MockTransport`` is
injected, so the service's matching + projection logic is exercised directly.
The connector is built from a resolved ``NinjaConfig`` (as the router does from
the encrypted app_settings), not from env.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from magister_api.ninja.client import NinjaClient, NinjaConfig
from magister_api.schemas.ninja import NinjaDeviceSummary
from magister_api.services.ninja import (
    NinjaConnectorService,
    NinjaNotConfiguredError,
    NinjaNotLinkedError,
    resolve_ninja_config,
    summarize_device,
)

_DETAIL = {
    "id": 10,
    "systemName": "pc-1",
    "dnsName": "pc-1.ad.local",
    "offline": False,
    "os": {"name": "Windows 11"},
    "nodeClass": "WINDOWS_WORKSTATION",
    "system": {"biosSerialNumber": "SN-1"},
    "organizationId": 3,
}

_CONFIG = NinjaConfig(region="eu", client_id="cid", client_secret="sec")


class _Handler:
    def __init__(self, *, devices: list[dict[str, Any]], scripts: list[dict[str, Any]]) -> None:
        self.devices = devices
        self.scripts = scripts
        self.ran: dict[str, Any] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if path == "/v2/devices":
            return httpx.Response(200, json=self.devices)
        if path == "/v2/device/10":
            return httpx.Response(200, json=_DETAIL)
        if path == "/v2/automation/scripts":
            return httpx.Response(200, json=self.scripts)
        if path == "/v2/device/10/script/run":
            import json as _json

            self.ran = _json.loads(request.content.decode())
            return httpx.Response(200, json={"jobId": 1})
        return httpx.Response(404, json={"error": "nf"})


def _service(
    handler: _Handler, *, enabled: bool = True
) -> tuple[NinjaConnectorService, NinjaClient]:
    client = NinjaClient(
        NinjaConfig(region="eu", client_id="c", client_secret="s"),
        transport=httpx.MockTransport(handler),
    )
    cfg = _CONFIG if enabled else None
    return NinjaConnectorService(cfg, client=client), client


def test_resolve_ninja_config_gates_on_enabled_and_completeness() -> None:
    def r(**kw: object) -> object:
        return resolve_ninja_config(**kw)  # type: ignore[arg-type]

    assert r(enabled=False, region="eu", client_id="a", client_secret="b") is None
    assert r(enabled=True, region="eu", client_id="a", client_secret="") is None
    assert r(enabled=True, region="", client_id="a", client_secret="b") is None
    cfg = resolve_ninja_config(enabled=True, region="eu", client_id="a", client_secret="b")
    assert cfg is not None and cfg.region == "eu" and cfg.client_id == "a"


def test_summarize_projects_defensively() -> None:
    s = summarize_device(_DETAIL)
    assert s == NinjaDeviceSummary(
        ninja_device_id=10,
        system_name="pc-1",
        dns_name="pc-1.ad.local",
        offline=False,
        os_name="Windows 11",
        serial_number="SN-1",
        node_class="WINDOWS_WORKSTATION",
        organization_id=3,
    )


async def test_status_disabled_shows_nothing() -> None:
    svc, client = _service(_Handler(devices=[], scripts=[]), enabled=False)
    try:
        out = await svc.status(name="pc-1", serial_number=None)
    finally:
        await client.aclose()
    assert out.enabled is False and out.matched is False


async def test_status_matched_returns_live_summary_and_scripts() -> None:
    h = _Handler(devices=[{"id": 10, "systemName": "pc-1"}], scripts=[{"id": 5, "name": "Reboot"}])
    svc, client = _service(h)
    try:
        out = await svc.status(name="PC-1", serial_number=None)
    finally:
        await client.aclose()
    assert out.enabled and out.matched and out.via == "hostname"
    assert out.status is not None and out.status.ninja_device_id == 10
    assert [s.name for s in out.scripts] == ["Reboot"]


async def test_status_no_match() -> None:
    svc, client = _service(_Handler(devices=[{"id": 10, "systemName": "other"}], scripts=[]))
    try:
        out = await svc.status(name="pc-1", serial_number="nope")
    finally:
        await client.aclose()
    assert out.enabled and not out.matched and out.status is None


async def test_status_survives_ninja_outage() -> None:
    # /v2/devices → 500 must yield a soft error, not raise.
    def boom(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(500, json={"error": "boom"})

    client = NinjaClient(_CONFIG, transport=httpx.MockTransport(boom))
    svc = NinjaConnectorService(_CONFIG, client=client)
    try:
        out = await svc.status(name="pc-1", serial_number=None)
    finally:
        await client.aclose()
    assert out.enabled and not out.matched and out.error is not None


async def test_run_script_rematches_and_runs() -> None:
    h = _Handler(devices=[{"id": 10, "systemName": "pc-1"}], scripts=[])
    svc, client = _service(h)
    try:
        ninja_id = await svc.run_script(
            name="pc-1", serial_number=None, script_id=5, parameters="--x"
        )
    finally:
        await client.aclose()
    assert ninja_id == 10
    assert h.ran == {"type": "SCRIPT", "id": 5, "parameters": "--x"}


async def test_run_script_refuses_when_unmatched() -> None:
    svc, client = _service(_Handler(devices=[{"id": 10, "systemName": "other"}], scripts=[]))
    try:
        with pytest.raises(NinjaNotLinkedError):
            await svc.run_script(name="pc-1", serial_number=None, script_id=5, parameters=None)
    finally:
        await client.aclose()


async def test_run_script_refuses_when_disabled() -> None:
    svc, client = _service(_Handler(devices=[], scripts=[]), enabled=False)
    try:
        with pytest.raises(NinjaNotConfiguredError):
            await svc.run_script(name="pc-1", serial_number=None, script_id=5, parameters=None)
    finally:
        await client.aclose()
