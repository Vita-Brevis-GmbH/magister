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

Seit 2026-11-16 trägt sie die Selbstprüfung der Anmeldung (``oidc``, ADR-0025
Nachtrag). Ein älteres Cockpit kennt das Feld nicht und weist die ganze
Meldung ab (HTTP 422, es prüft streng). Dann geht sie einmal ohne ``oidc``
noch einmal hinaus — so kommt es auf die Reihenfolge der Updates nicht an.

Ebenso ``rollen_fremd`` (ADR-0027): solange das Cockpit die Rollen führt, die
Rollen aus anderer Quelle — Benutzername, Kennung, Rolle, Herkunft, sonst
nichts —, damit das Cockpit sie zeigen und entziehen lassen kann.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.factory import ad_backend, ad_missing_settings
from magister_api.auth.effective_settings import load_effective_settings
from magister_api.config import Settings
from magister_api.models.ad_sync_state import AdSyncState
from magister_api.models.audit import AuditEvent
from magister_api.modules import catalog
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.foreign_roles import foreign_roles_report
from magister_api.services.local_admin_mfa import LocalAdminMfaService
from magister_api.services.role_lock import roles_from_cockpit
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


async def _local_admin(session: AsyncSession, base: Settings) -> dict[str, Any]:
    """Gibt es das lokale Admin-Konto, und hat es einen zweiten Faktor?

    Ohne Konto und ohne OIDC kommt niemand ins Portal ("Kein Anmeldeweg
    eingerichtet") — das soll die Konsole sehen, bevor der Kunde anruft.
    Nur Name und Zustand; kein Hash, kein TOTP-Geheimnis.
    """
    admin = await LocalAdminRepository(session).get()
    if admin is None:
        return {"exists": False}
    mfa = await LocalAdminMfaService(session, base).status()
    return {
        "exists": True,
        "enabled": bool(admin.enabled),
        "username": admin.username,
        "mfa_enrolled": bool(mfa and mfa.enrolled),
        "locked": admin.locked_until is not None,
    }


async def collect_status(
    session: AsyncSession,
    base: Settings,
    tenant: Tenant,
    *,
    reconcile: dict[str, Any],
    maintenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Die Meldung für einen Kunden zusammenstellen. Liest nur, schreibt nichts.

    Ohne die Selbstprüfung der Anmeldung (``oidc``): die geht ins Netz und
    kommt ausserhalb der Datenbanksitzung dazu
    (:func:`magister_api.services.reconcile_loop._report`).

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
            "mail_secret": bool(secrets.mail_secret),
        },
        "maintenance": maintenance or [],
        "local_admin": await _local_admin(session, base),
    }
    secrets_key = keys_for(session, base).secrets_key
    if secrets_key:
        public = public_key_b64(secrets_key)
        report["sealed_public_key"] = public
        report["sealed_key_id"] = key_id(public)
    platform_key = base.platform_secrets_key.get_secret_value()
    if platform_key:
        # Für alle Kunden derselbe: die Konsole versiegelt den Plattform-
        # Standard damit (ADR-0024 D3, Plattform-Geheimnisse).
        platform_public = public_key_b64(platform_key)
        report["platform_sealed_public_key"] = platform_public
        report["platform_sealed_key_id"] = key_id(platform_public)
    if await roles_from_cockpit(session):
        # Nur solange das Cockpit die Rollen führt: sonst vergibt der Kunde
        # selbst, und jede Rolle wäre „fremd".
        report["rollen_fremd"] = await foreign_roles_report(session, base)
    return report


#: Felder, die ein älteres Cockpit noch nicht kennt. Weist es die Meldung mit
#: 422 ab, geht sie einmal ohne die beanstandeten dieser Felder hinaus (ohne
#: alle, wenn die Antwort keines nennt).
OPTIONAL_FIELDS = ("oidc", "rollen_fremd")
#: Mandanten (Konsolen-Id), für die das Weglassen schon im Protokoll steht —
#: einmal je Prozess als Warnung, danach leiser; die Meldung läuft alle paar
#: Minuten, und bis zum Update des Cockpits ist das der Normalfall.
_without_optional_logged: set[str] = set()


async def post_status(
    console_url: str,
    tenant_console_id: str,
    report: dict[str, Any],
    *,
    token: str,
    management_marker: str = "",
    timeout_s: float = 5.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Die Meldung abschicken. Wirft :class:`ReportRejectedError`, wenn sie nicht ankam.

    Antwortet das Cockpit mit 422 und trägt die Meldung ein Feld aus
    :data:`OPTIONAL_FIELDS`, geht sie einmal ohne diese Felder hinaus. Das
    ist der Weg für ein Cockpit, das älter ist als Magister (es prüft mit
    ``extra=forbid``). Eine Fähigkeit, nach der man fragen könnte, gibt es im
    Vertrag nicht (weder im Soll-Zustand noch in der Antwort auf die Meldung),
    und eine neue bräuchte selbst wieder ein Update des Cockpits zuerst. Kosten:
    eine zweite Anfrage je Meldung, solange das Cockpit älter ist. Scheitert
    auch sie, gilt die Meldung wie bisher als nicht angekommen.
    """
    url = f"{console_base(console_url)}/tenants/{tenant_console_id}/status"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if management_marker:
        headers["X-Magister-Management"] = management_marker
    optional = [k for k in OPTIONAL_FIELDS if k in report]
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s, verify=console_verify(), transport=transport
        ) as client:
            response = await client.post(url, headers=headers, json=report)
            if response.status_code == 422 and optional:
                # Nur, was das Cockpit beanstandet: ein Cockpit, das `oidc`
                # schon kennt und `rollen_fremd` noch nicht, bekommt `oidc`
                # weiter. Nennt die Antwort keines, gehen alle.
                dropped = _rejected_optional(response, optional) or optional
                _log_without_optional(tenant_console_id, dropped, response)
                reduced = {k: v for k, v in report.items() if k not in dropped}
                response = await client.post(url, headers=headers, json=reduced)
            elif response.status_code in (200, 204):
                _without_optional_logged.discard(tenant_console_id)
    except (httpx.HTTPError, ConsoleTlsError) as exc:
        raise ReportRejectedError(f"Konsole nicht erreichbar: {exc}") from exc
    if response.status_code not in (200, 204):
        raise ReportRejectedError(
            f"Konsole antwortete mit HTTP {response.status_code} auf die Zustandsmeldung."
        )


def _log_without_optional(
    tenant_console_id: str, fields: list[str], response: httpx.Response
) -> None:
    first = tenant_console_id not in _without_optional_logged
    _without_optional_logged.add(tenant_console_id)
    logger.log(
        logging.WARNING if first else logging.DEBUG,
        "Konsole weist die Zustandsmeldung ab (HTTP 422, %s) — erneut ohne %s gesendet "
        "(ein Cockpit, das älter ist als dieses Feld?).",
        _rejected_fields(response),
        ", ".join(fields),
    )


def _rejected_optional(response: httpx.Response, optional: list[str]) -> list[str]:
    """Die Felder aus ``optional``, die die 422-Antwort beanstandet (``body.<feld>``)."""
    try:
        body: Any = response.json()
    except ValueError:
        return []
    detail: Any = cast(dict[str, Any], body).get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, list):
        return []
    named: set[str] = set()
    for item in cast(list[Any], detail):
        loc: Any = cast(dict[str, Any], item).get("loc") if isinstance(item, dict) else None
        if isinstance(loc, list) and len(cast(list[Any], loc)) >= 2:
            where = cast(list[Any], loc)
            if where[0] == "body" and where[1] in optional:
                named.add(str(where[1]))
    return [k for k in optional if k in named]


def _rejected_fields(response: httpx.Response) -> str:
    """Die beanstandeten Felder aus der 422-Antwort (``body.oidc``), ohne Werte.

    FastAPI nennt unter ``detail`` auch den eingereichten Wert (``input``); der
    kommt nicht ins Protokoll, nur der Ort und die Art.
    """
    try:
        body: Any = response.json()
    except ValueError:
        return "ohne Angabe"
    detail: Any = cast(dict[str, Any], body).get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, list):
        return "ohne Angabe"
    places: list[str] = []
    for item in cast(list[Any], detail)[:5]:
        if not isinstance(item, dict):
            continue
        entry = cast(dict[str, Any], item)
        loc: Any = entry.get("loc")
        kind: Any = entry.get("type")
        where = ".".join(str(p) for p in cast(list[Any], loc)) if isinstance(loc, list) else "?"
        places.append(f"{where}: {kind}" if isinstance(kind, str) else where)
    return "; ".join(places)[:300] or "ohne Angabe"


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


__all__ = ["OPTIONAL_FIELDS", "collect_status", "post_status", "reconcile_outcome"]
