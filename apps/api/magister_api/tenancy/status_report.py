"""Zustandsmeldung an die Konsole (ADR-0024 D1).

Nach jedem Abgleich meldet die Datenebene je Kunde, **was bei ihr wirklich
gilt**: ob der Abgleich gelang, welches Profil und welche Module wirksam
sind, wie der AD-Sync steht, welche Geheimnisse gesetzt sind (nur ob, nie
was) und wie Wartungsaufträge ausgegangen sind.

Der Grund: von der Konsole aus war bisher nicht zu sehen, ob eine Einstellung
ankommt. „In der Konsole auf Firma gestellt, das Portal zeigt Schule" konnte
ein Abgleich sein, der gar nicht läuft — und das wusste niemand, ausser wer
die Logs der Datenebene las.

Was diese Meldung **nicht** trägt: Personendaten, Namen, DSNs, Geheimnisse.
Zeitpunkte, Zählerstände, Schlüsselnamen, Ursachen-Codes. Und wie die
Schemastand-Meldung: scheitert sie, ist das eine Warnung, kein Fehler — der
Betrieb hängt nicht an der Konsole.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.factory import ad_backend, ad_missing_settings
from magister_api.auth.effective_settings import load_effective_settings
from magister_api.config import Settings
from magister_api.models.ad_sync_state import AdSyncState
from magister_api.models.audit import AuditEvent
from magister_api.modules import catalog
from magister_api.services.app_settings import AppSettingsService
from magister_api.tenancy.console_report import ReportRejectedError, console_base
from magister_api.tenancy.console_tls import ConsoleTlsError, console_verify
from magister_api.tenancy.keys import keys_for
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.sealing import key_id, public_key_b64

logger = logging.getLogger(__name__)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


async def _last_event(session: AsyncSession, action: str) -> datetime | None:
    """Zeitpunkt des letzten Ereignisses dieser Art.

    `# scope-bypass: gelesen wird nur der Zeitpunkt eines Systemereignisses
    (AD-Sync), keine Personendaten und kein Payload.`
    """
    stmt = select(func.max(AuditEvent.ts)).where(AuditEvent.action == action)
    return (await session.execute(stmt)).scalar_one_or_none()


async def collect_status(
    session: AsyncSession,
    base: Settings,
    tenant: Tenant,
    *,
    reconcile: dict[str, Any],
    maintenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Die Meldung für einen Kunden zusammenstellen. Liest nur, schreibt nichts.

    `# scope-bypass: app_settings und ad_sync_state sind Singletons je
    Kundenschema ohne Schul-Scope.`
    """
    modules = await AppSettingsService(session, base).get_module_settings()
    effective = await load_effective_settings(session, base)
    backend = ad_backend(base, tenant)
    missing = ad_missing_settings(effective, backend)
    state = (
        await session.execute(select(AdSyncState).where(AdSyncState.id == 1))
    ).scalar_one_or_none()

    secrets = await AppSettingsService(session, base).get_effective()
    report: dict[str, Any] = {
        "reconcile": reconcile,
        "effective_profile": modules.instance_profile,
        "enabled_modules": catalog.effective_enabled_ids(
            modules.instance_profile, modules.module_overrides
        ),
        "ad": {
            "configured": not missing,
            "missing": missing,
            "backend": backend,
            "last_success_at": _iso(await _last_event(session, "ad_sync_completed")),
            "last_failure_at": _iso(await _last_event(session, "ad_sync_failed")),
            "last_count": state.last_synced_count if state else None,
            "last_mode": state.last_mode if state else None,
        },
        "secrets_present": {
            "oidc_client_secret": bool(secrets.oidc_client_secret),
            "ninja_client_secret": bool(secrets.ninja_client_secret),
        },
        "maintenance": maintenance or [],
    }
    secrets_key = keys_for(session, base).secrets_key
    if secrets_key:
        public = public_key_b64(secrets_key)
        report["sealed_public_key"] = public
        report["sealed_key_id"] = key_id(public)
    return report


async def post_status(
    console_url: str,
    tenant_console_id: str,
    report: dict[str, Any],
    *,
    token: str,
    management_marker: str = "",
    timeout_s: float = 5.0,
) -> None:
    """Die Meldung abschicken. Wirft :class:`ReportRejectedError`, wenn sie nicht ankam."""
    url = f"{console_base(console_url)}/tenants/{tenant_console_id}/status"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if management_marker:
        headers["X-Magister-Management"] = management_marker
    try:
        async with httpx.AsyncClient(timeout=timeout_s, verify=console_verify()) as client:
            response = await client.post(url, headers=headers, json=report)
    except (httpx.HTTPError, ConsoleTlsError) as exc:
        raise ReportRejectedError(f"Konsole nicht erreichbar: {exc}") from exc
    if response.status_code not in (200, 204):
        raise ReportRejectedError(
            f"Konsole antwortete mit HTTP {response.status_code} auf die Zustandsmeldung."
        )


def reconcile_outcome(
    *, ok: bool, touched: bool = False, error: str | None = None
) -> dict[str, Any]:
    return {
        "ok": ok,
        "at": datetime.now(UTC).isoformat(),
        "touched": touched,
        # Ein Satz, gekürzt. Die Fehlermeldungen des Abholers tragen weder
        # Token noch Antwortkörper (siehe desired_state.fetch_desired_state).
        "error": (error or None) and error[:500],
    }


__all__ = ["collect_status", "post_status", "reconcile_outcome"]
