"""System operations: record WebUI-triggered restart / git-update requests.

Security model (deliberate): the API container is unprivileged and has NO
access to the Docker socket or the host. It therefore never restarts or rebuilds
anything itself. Instead it drops a small JSON *request* file into a directory
shared with the host (``<ops_dir>/requests/<id>.json``). A privileged host-side
watcher (systemd timer, see ``deploy/ops-agent/``) picks the request up, runs the
actual ``git pull`` / ``docker compose build`` / ``restart`` and writes the
outcome back to ``<ops_dir>/status.json``, which the API reads for display.

So a compromise of the WebUI can at most enqueue a restart/update command — it
can never execute arbitrary host commands.
"""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.base import utcnow

ALLOWED_ACTIONS: tuple[str, ...] = ("restart", "update")


class SystemOpsNotConfiguredError(RuntimeError):
    """Raised when no ops directory is configured (controls are disabled)."""


def _write_request(req_dir: str, cmd_id: str, payload: dict[str, Any]) -> None:
    """Atomically publish a request file (sync; called via a threadpool)."""
    os.makedirs(req_dir, exist_ok=True)
    tmp = os.path.join(req_dir, f".{cmd_id}.json.tmp")
    final = os.path.join(req_dir, f"{cmd_id}.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, final)


class SystemOpsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self._settings = settings
        self.audit = AuditService(session, settings)

    @property
    def _ops_dir(self) -> str | None:
        return self._settings.ops_dir

    async def enqueue(
        self,
        action: str,
        *,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        """Write a command-request file for the host watcher and audit it.

        Raises ``ValueError`` for an unknown action, ``SystemOpsNotConfigured``
        when no ops directory is available.
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unknown_action:{action}")
        ops = self._ops_dir
        if not ops:
            raise SystemOpsNotConfiguredError("ops_dir_not_configured")

        cmd_id = uuid4().hex
        payload: dict[str, Any] = {
            "id": cmd_id,
            "action": action,
            "actor_upn": actor_upn,
            "requested_at": utcnow().isoformat(),
        }
        # Atomic publish (off the event loop) so the watcher never reads a
        # half-written file and the request never blocks the async path.
        await run_in_threadpool(_write_request, os.path.join(ops, "requests"), cmd_id, payload)

        await self.audit.emit(
            action="system_command_requested",
            target_kind="system",
            target_id=action,
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"command": action, "command_id": cmd_id},
        )
        return payload

    def status(self) -> dict[str, Any]:
        """Read the current ops status (pending count + last watcher result)."""
        ops = self._ops_dir
        out: dict[str, Any] = {"configured": bool(ops), "pending": 0, "last": None}
        if not ops:
            return out
        req_dir = os.path.join(ops, "requests")
        if os.path.isdir(req_dir):
            out["pending"] = sum(1 for f in os.listdir(req_dir) if f.endswith(".json"))
        status_path = os.path.join(ops, "status.json")
        if os.path.isfile(status_path):
            try:
                with open(status_path, encoding="utf-8") as fh:
                    out["last"] = json.load(fh)
            except (OSError, ValueError):
                out["last"] = None
        return out


__all__ = ["ALLOWED_ACTIONS", "SystemOpsNotConfiguredError", "SystemOpsService"]
