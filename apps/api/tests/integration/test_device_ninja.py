"""Integration: NinjaOne detail-view endpoints (GET status, POST run-script).

Postgres-gated. The NinjaOne HTTP layer is served by an ``httpx.MockTransport``
injected in place of the real client, so no external tenant is needed. The
connector config lives (encrypted) in ``app_settings`` and is enabled per test.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession as SASession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.ninja.client import NinjaClient as RealNinjaClient
from magister_api.schemas.app_settings import AppSettingsUpdate
from magister_api.services.app_settings import AppSettingsService

pytestmark = pytest.mark.postgres

_DETAIL = {
    "id": 10,
    "systemName": "pc-ninja",
    "dnsName": "pc-ninja.ad.local",
    "offline": False,
    "os": {"name": "Windows 11"},
    "system": {"biosSerialNumber": "SN-9"},
    "nodeClass": "WINDOWS_WORKSTATION",
}


def _make_handler(devices: list[dict[str, Any]], scripts: list[dict[str, Any]]):
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if p == "/v2/devices":
            return httpx.Response(200, json=devices)
        if p == "/v2/device/10":
            return httpx.Response(200, json=_DETAIL)
        if p == "/v2/automation/scripts":
            return httpx.Response(200, json=scripts)
        if p == "/v2/device/10/script/run":
            return httpx.Response(200, json={"jobId": 7})
        return httpx.Response(404, json={"error": "nf"})

    return handler


def _install_fake_ninja(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    def factory(config: Any) -> RealNinjaClient:
        return RealNinjaClient(config, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("magister_api.services.ninja.NinjaClient", factory)


async def _enable_ninja(db_session: SASession, settings: Settings) -> None:
    await AppSettingsService(db_session, settings).update(
        AppSettingsUpdate(
            ninja_enabled=True,
            ninja_region="eu",
            ninja_client_id="cid",
            ninja_client_secret="the-ninja-secret",
        ),
        actor_upn="admin@example.ch",
        actor_object_guid=None,
        ip=None,
        request_id="ninja-enable",
    )
    await db_session.commit()


async def _create_device(as_admin: AsyncClient, name: str) -> int:
    r = await as_admin.post("/devices", json={"name": name, "serial_number": "SN-9"})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


async def _actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list(
            (await s.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
        )


async def test_requires_smi(as_schulleitung_a: AsyncClient) -> None:
    # Auth runs before the route body, so the device id need not exist.
    assert (await as_schulleitung_a.get("/devices/1/ninja")).status_code == 403
    r = await as_schulleitung_a.post("/devices/1/ninja/run-script", json={"script_id": 1})
    assert r.status_code == 403


async def test_device_not_found(as_admin: AsyncClient) -> None:
    assert (await as_admin.get("/devices/999999/ninja")).status_code == 404


async def test_status_shows_nothing_when_disabled(as_admin: AsyncClient) -> None:
    did = await _create_device(as_admin, "PC-OFF")
    r = await as_admin.get(f"/devices/{did}/ninja")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False and body["matched"] is False


async def test_status_matched_and_run_script_is_audited(
    as_admin: AsyncClient,
    db_session: SASession,
    app_settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_ninja(db_session, app_settings)
    _install_fake_ninja(
        monkeypatch,
        _make_handler([{"id": 10, "systemName": "pc-ninja"}], [{"id": 5, "name": "Reboot"}]),
    )
    did = await _create_device(as_admin, "PC-NINJA")

    r = await as_admin.get(f"/devices/{did}/ninja")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] and body["matched"] and body["via"] == "hostname"
    assert body["status"]["ninja_device_id"] == 10
    assert body["status"]["system_name"] == "pc-ninja"
    assert [s["name"] for s in body["scripts"]] == ["Reboot"]

    r = await as_admin.post(
        f"/devices/{did}/ninja/run-script", json={"script_id": 5, "parameters": "--secret-arg"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "ninja_device_id": 10, "detail": None}

    assert "ninja_script_run" in await _actions(engine)
    # The audit event records the run but never the parameter content or the
    # connector secret.
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        rid = (
            await s.execute(select(AuditEvent.id).where(AuditEvent.action == "ninja_script_run"))
        ).scalar_one()
        rec = await AuditService(s, app_settings).read(rid)
    assert rec is not None
    assert rec.payload.get("script_id") == 5
    assert rec.payload.get("ninja_device_id") == 10
    assert rec.payload.get("params_set") is True
    assert "--secret-arg" not in str(rec.payload)
    assert "the-ninja-secret" not in str(rec.payload)


async def test_run_script_refuses_when_no_match(
    as_admin: AsyncClient,
    db_session: SASession,
    app_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_ninja(db_session, app_settings)
    # NinjaOne has a device, but none matching this Magister device.
    _install_fake_ninja(monkeypatch, _make_handler([{"id": 10, "systemName": "somethingelse"}], []))
    did = await _create_device(as_admin, "PC-UNMATCHED")
    r = await as_admin.post(f"/devices/{did}/ninja/run-script", json={"script_id": 5})
    assert r.status_code == 409
    assert r.json()["detail"] == "ninja_device_not_linked"
