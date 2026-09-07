"""NinjaOne connector service — live status + on-demand script runs.

Deliberately DB-free: it takes a device's ``name``/``serial_number`` and talks
only to NinjaOne. Nothing is persisted — the match is recomputed on every call,
so the connector can be swapped or disabled without touching Magister data. The
router loads the device (scope-checked, via ``DeviceService``), then hands the
two fields here; on a script run the router writes the audit event.

Security: a script run never trusts a client-supplied NinjaOne id. The service
re-matches from the Magister device, so an operator can only run a script on the
device Magister actually maps to.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from typing import Any

from magister_api.ninja.client import (
    NinjaApiError,
    NinjaClient,
    NinjaConfig,
    NinjaError,
    NinjaNotConfiguredError,
)
from magister_api.ninja.match import match_device, ninja_serial
from magister_api.schemas.ninja import (
    NinjaDeviceSummary,
    NinjaScriptOut,
    NinjaStatusOut,
)


class NinjaNotLinkedError(NinjaError):
    """A script run was requested but the Magister device matches no NinjaOne one."""


def resolve_ninja_config(
    *,
    enabled: bool,
    region: str | None,
    client_id: str | None,
    client_secret: str | None,
) -> NinjaConfig | None:
    """Build a ``NinjaConfig`` from the decrypted app_settings, or ``None`` when
    the connector is disabled or incompletely configured."""
    if not enabled:
        return None
    cfg = NinjaConfig(
        region=region or "",
        client_id=client_id or "",
        client_secret=client_secret or "",
    )
    return cfg if cfg.is_complete() else None


def summarize_device(dev: dict[str, Any]) -> NinjaDeviceSummary:
    """Defensive projection of a NinjaOne device payload to the UI summary."""
    os_obj = dev.get("os")
    os_name = os_obj.get("name") if isinstance(os_obj, dict) else None
    return NinjaDeviceSummary(
        ninja_device_id=int(dev["id"]),
        system_name=_as_str(dev.get("systemName")),
        dns_name=_as_str(dev.get("dnsName")),
        offline=dev.get("offline") if isinstance(dev.get("offline"), bool) else None,
        last_contact=_as_float(dev.get("lastContact")),
        os_name=_as_str(os_name),
        serial_number=ninja_serial(dev) or None,
        node_class=_as_str(dev.get("nodeClass")),
        organization_id=dev.get("organizationId")
        if isinstance(dev.get("organizationId"), int)
        else None,
    )


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


class NinjaConnectorService:
    def __init__(self, config: NinjaConfig | None, *, client: NinjaClient | None = None) -> None:
        self._config = config
        self._override = client

    @property
    def enabled(self) -> bool:
        return self._config is not None

    def _build_client(self) -> NinjaClient:
        if self._override is not None:
            return self._override
        if self._config is None:
            raise NinjaNotConfiguredError("ninja_not_configured")
        return NinjaClient(self._config)

    @contextlib.asynccontextmanager
    async def _client(self) -> AsyncGenerator[NinjaClient]:
        client = self._build_client()
        try:
            yield client
        finally:
            # Only close clients we built; an injected (test) client is owned
            # by the caller.
            if self._override is None:
                await client.aclose()

    async def status(self, *, name: str | None, serial_number: str | None) -> NinjaStatusOut:
        """Live status of the matched NinjaOne device + the script library.

        Never raises for an operational failure — NinjaOne being down or an odd
        payload yields ``error``/empty rather than a 500, because this only feeds
        a read-only panel.
        """
        if not self.enabled:
            return NinjaStatusOut(enabled=False)
        async with self._client() as client:
            try:
                devices = await client.list_devices()
            except NinjaError as exc:
                return NinjaStatusOut(enabled=True, error=str(exc))

            result = match_device(name=name, serial_number=serial_number, ninja_devices=devices)
            if not result.matched or result.ninja_device_id is None:
                return NinjaStatusOut(
                    enabled=True, matched=False, ambiguous=result.ambiguous, via=result.via
                )

            detail = self._device_detail(client, devices, result.ninja_device_id)
            summary = summarize_device(await detail)
            scripts = await self._scripts(client)
            return NinjaStatusOut(
                enabled=True,
                matched=True,
                via=result.via,
                status=summary,
                scripts=scripts,
            )

    @staticmethod
    async def _device_detail(
        client: NinjaClient, listed: list[dict[str, Any]], ninja_device_id: int
    ) -> dict[str, Any]:
        """Fetch the detailed device; fall back to the summary row on failure."""
        try:
            return await client.get_device(ninja_device_id)
        except NinjaError:
            for dev in listed:
                if dev.get("id") == ninja_device_id:
                    return dev
            return {"id": ninja_device_id}

    @staticmethod
    async def _scripts(client: NinjaClient) -> list[NinjaScriptOut]:
        """Best-effort script library — an unverified endpoint must not break status."""
        try:
            raw = await client.list_scripts()
        except NinjaError:
            return []
        out: list[NinjaScriptOut] = []
        for item in raw:
            sid = item.get("id")
            name = item.get("name")
            if isinstance(sid, int) and isinstance(name, str):
                out.append(NinjaScriptOut(id=sid, name=name))
        return out

    async def run_script(
        self,
        *,
        name: str | None,
        serial_number: str | None,
        script_id: int,
        parameters: str | None,
    ) -> int:
        """Re-match, then run the library script. Returns the NinjaOne device id.

        Raises ``NinjaNotConfiguredError`` when disabled, ``NinjaNotLinkedError``
        when the device maps to no (or an ambiguous) NinjaOne device, and
        ``NinjaApiError``/``NinjaError`` on an API failure.
        """
        if not self.enabled:
            raise NinjaNotConfiguredError("ninja_not_configured")
        async with self._client() as client:
            devices = await client.list_devices()
            result = match_device(name=name, serial_number=serial_number, ninja_devices=devices)
            if not result.matched or result.ninja_device_id is None:
                raise NinjaNotLinkedError("ninja_device_not_linked")
            await client.run_script(
                result.ninja_device_id, script_id=script_id, parameters=parameters
            )
            return result.ninja_device_id


__all__ = [
    "NinjaApiError",
    "NinjaConnectorService",
    "NinjaError",
    "NinjaNotConfiguredError",
    "NinjaNotLinkedError",
    "resolve_ninja_config",
    "summarize_device",
]
