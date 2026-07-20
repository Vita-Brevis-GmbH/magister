"""System-ops endpoints: enqueue restart/update requests + read status."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from magister_api.config import Settings
from magister_api.services.system_ops import SystemOpsNotConfiguredError, SystemOpsService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres


class TestRbacAndConfig:
    async def test_status_requires_admin(self, as_schulleitung_a: AsyncClient) -> None:
        assert (await as_schulleitung_a.get("/admin/system/status")).status_code == 403

    async def test_restart_rejects_anonymous(self, client: AsyncClient) -> None:
        # Anonymous is rejected before any ops action (401 auth or 403 CSRF).
        assert (await client.post("/admin/system/restart")).status_code in (401, 403)

    async def test_unconfigured_status_is_false(self, as_admin: AsyncClient) -> None:
        body = (await as_admin.get("/admin/system/status")).json()
        assert body["configured"] is False
        assert body["pending"] == 0
        assert body["last"] is None

    async def test_unconfigured_enqueue_is_503(self, as_admin: AsyncClient) -> None:
        # The default test settings have no ops_dir → controls disabled.
        assert (await as_admin.post("/admin/system/update")).status_code == 503


class TestEnqueueService:
    async def test_enqueue_writes_request_and_status_reflects_it(
        self, engine: AsyncEngine, app_settings: Settings, tmp_path: os.PathLike[str]
    ) -> None:
        settings = app_settings.model_copy(update={"ops_dir": str(tmp_path)})
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            svc = SystemOpsService(s, settings)
            payload = await svc.enqueue(
                "update",
                actor_upn="admin@example.ch",
                actor_object_guid=None,
                ip=None,
                request_id="req-x",
            )
            await s.commit()

        # A request file landed in <ops>/requests.
        req_dir = os.path.join(str(tmp_path), "requests")
        files = [f for f in os.listdir(req_dir) if f.endswith(".json")]
        assert len(files) == 1
        body = json.loads(Path(req_dir, files[0]).read_text(encoding="utf-8"))  # noqa: ASYNC240
        assert body["action"] == "update"
        assert body["id"] == payload["id"]

        # Status reports the pending request and, once the watcher writes a
        # status.json, surfaces its last result.
        async with sm() as s:
            svc = SystemOpsService(s, settings)
            assert svc.status()["pending"] == 1
        Path(str(tmp_path), "status.json").write_text(  # noqa: ASYNC240
            json.dumps({"action": "update", "state": "success", "git_sha": "abc123"}),
            encoding="utf-8",
        )
        async with sm() as s:
            last = SystemOpsService(s, settings).status()["last"]
        assert last is not None
        assert last["state"] == "success"
        assert last["git_sha"] == "abc123"

    async def test_unknown_action_rejected(
        self, engine: AsyncEngine, app_settings: Settings, tmp_path: os.PathLike[str]
    ) -> None:
        settings = app_settings.model_copy(update={"ops_dir": str(tmp_path)})
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            with pytest.raises(ValueError, match="unknown_action"):
                await SystemOpsService(s, settings).enqueue(
                    "rm-rf",
                    actor_upn="a@example.ch",
                    actor_object_guid=None,
                    ip=None,
                    request_id="r",
                )

    async def test_not_configured_raises(self, engine: AsyncEngine, app_settings: Settings) -> None:
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            with pytest.raises(SystemOpsNotConfiguredError):
                await SystemOpsService(s, app_settings).enqueue(
                    "restart",
                    actor_upn="a@example.ch",
                    actor_object_guid=None,
                    ip=None,
                    request_id="r",
                )
