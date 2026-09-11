"""Tiefer Gesundheitszustand je Kundenseite — für die Überwachung.

`/healthz` sagt „der Prozess lebt". Das ist, was ein Orchestrierer braucht, und
es ist zu wenig für einen Betreiber: ein Prozess lebt auch dann, wenn die
Datenbank weg ist, das Schema hinterherhängt, der Kundenschlüssel fehlt oder
der AD-Abgleich seit drei Tagen scheitert. Genau diese vier Fälle sind die,
die zu einem Anruf führen.

**Warum die Prüfung ohne die Mandanten-Middleware läuft.** Ein Mandant mit
abweichendem Schemastand, fehlendem Schlüssel oder gesperrtem Zustand
bekommt von der Middleware ein `503 maintenance` — bevor irgendeine Route
läuft. Eine Sonde dahinter könnte also nie sagen, *warum*. Sie muss den
Mandanten deshalb selbst auflösen und beantwortet genau die Fälle, in denen
der Anfragepfad schweigt.

**Was hier bewusst nicht geprüft wird:** eine Verbindung zum Verzeichnis. Eine
Sonde, die im Minutentakt LDAP anfasst, ist bei zwanzig Kunden eine Last auf
zwanzig fremden Domänencontrollern — und über den Connector wäre sie ein
Auftrag je Abfrage. Stattdessen wird das **Alter des letzten Abgleichs**
gelesen: es steht in der Datenbank, kostet nichts und sagt dasselbe, nur
einen Takt später.

Die Stufen sind die von ADR-0021 D6 (0 in Ordnung, 1 Warnung, 2 kritisch) —
dieselbe Konvention wie `fleet_check`, damit die Überwachung nicht zwei
Zahlenwelten unterscheiden muss.
"""

from __future__ import annotations

import logging
import secrets as secretlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from magister_api.config import Settings, get_settings
from magister_api.models.ad_sync_state import AdSyncState
from magister_api.tenancy.context import get_engines
from magister_api.tenancy.keys import attach_keys, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant, TenantRegistry, TenantStatus
from magister_api.tenancy.scope import apply_tenant_scope
from magister_api.tenancy.version import HEAD_REVISION

logger = logging.getLogger(__name__)

OK = 0
WARNING = 1
CRITICAL = 2

STATE_NAMES = {OK: "ok", WARNING: "warning", CRITICAL: "critical"}

#: Ab wie vielen versäumten Abgleichen es ein Befund ist. Drei und nicht einer:
#: ein einzelner ausgefallener Lauf ist ein Neustart, ein Wartungsfenster beim
#: Kunden oder ein Domänencontroller im Update. Drei hintereinander sind ein
#: Zustand.
SYNC_MISSED_WARNING = 3

#: Ab hier ist es kritisch: einen Tag ohne Abgleich heisst, dass neue Konten
#: nicht ankommen und ausgetretene noch in den Listen stehen.
SYNC_CRITICAL_HOURS = 24


def require_health_token(request: Request) -> None:
    """Der Riegel vor der tiefen Sonde.

    Eine Abhängigkeit und keine Prüfung im Rumpf: so steht sie im
    Abhängigkeitsbaum der Route und der Architektur-Test sieht, dass diese
    Route bewacht ist. Dieselbe Bauart wie ``require_rpc_secret`` an der
    AD-Grenze — sitzungslos, aber nicht offen.

    **404 und nicht 401**: ohne gesetzten Token gibt es die Route nicht, und
    mit falschem Token soll sie genauso aussehen. Wer rät, soll nicht
    erfahren, dass er nah dran war.
    """
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    expected = settings.health_token.get_secret_value() if settings.health_token else ""
    presented = request.headers.get("x-magister-health") or request.query_params.get("token")
    if not expected or not secretlib.compare_digest(presented or "", expected):
        raise HTTPException(status_code=404, detail="Not Found")


@dataclass(frozen=True, slots=True)
class Check:
    """Eine Einzelprüfung. `detail` ist für Menschen, `name` für die Überwachung."""

    name: str
    status: int
    detail: str


@dataclass(frozen=True, slots=True)
class StackHealth:
    tenant_slug: str | None
    status: int
    checks: list[Check]

    @property
    def state(self) -> str:
        return STATE_NAMES[self.status]

    def as_dict(self, *, version: str) -> dict[str, object]:
        return {
            # `status` ist der Wert, den die Überwachung liest. Zuerst, damit
            # er in jedem Auszug sichtbar ist.
            "status": self.status,
            "state": self.state,
            "tenant": self.tenant_slug,
            "version": version,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks
            ],
        }


SessionFactoryFor = Callable[[Tenant], async_sessionmaker[AsyncSession]]


def _default_session_factory(tenant: Tenant) -> async_sessionmaker[AsyncSession]:
    return get_engines().sessionmaker_for(tenant)


def _status_check(tenant: Tenant) -> Check:
    if tenant.status is TenantStatus.ACTIVE:
        return Check("tenant_status", OK, "aktiv")
    if tenant.status is TenantStatus.SUSPENDED:
        # Gesperrt ist eine Entscheidung, kein Defekt — aber die Seite
        # antwortet dem Kunden mit 503, und wer die Überwachung liest, soll
        # nicht nach einer Störung suchen.
        return Check("tenant_status", WARNING, "gesperrt (Entscheidung, keine Störung)")
    return Check("tenant_status", CRITICAL, f"Zustand {tenant.status.value} — wird nicht bedient")


def _schema_check(tenant: Tenant) -> Check:
    if not tenant.schema_version:
        return Check(
            "schema_version",
            OK,
            "kein Stand gemeldet (Bestand vor dem Schema-Umzug) — wird bedient",
        )
    if tenant.schema_version == HEAD_REVISION:
        return Check("schema_version", OK, f"auf dem Kopfstand {HEAD_REVISION}")
    return Check(
        "schema_version",
        CRITICAL,
        f"Schema steht auf {tenant.schema_version}, der Code auf {HEAD_REVISION} — "
        "die Seite antwortet mit Wartung, bis die Migration gelaufen ist",
    )


def _key_check(tenant: Tenant, registry: TenantRegistry, settings: Settings) -> Check:
    try:
        resolve_tenant_keys(
            tenant.slug,
            fallback_audit_key=settings.audit_key.get_secret_value(),
            fallback_audit_key_id=settings.audit_key_id,
            fallback_secrets_key=settings.secrets_key.get_secret_value(),
            single_tenant=len(registry.tenants) == 1,
        )
    except Exception as exc:
        # Der Grund nennt eine Umgebungsvariable, kein Geheimnis — und er ist
        # genau die Auskunft, die den Betriebsfehler behebt.
        return Check("tenant_key", CRITICAL, f"kein Kundenschlüssel: {exc}")
    return Check("tenant_key", OK, "vorhanden")


def _sync_check(state: AdSyncState | None, settings: Settings) -> Check:
    if state is None:
        return Check("ad_sync", WARNING, "noch nie gelaufen")
    last = state.last_full_sync_at
    if last is None:
        return Check("ad_sync", WARNING, "noch kein vollständiger Abgleich")
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    age = datetime.now(UTC) - last
    minutes = age.total_seconds() / 60
    interval = max(1, settings.ad_sync_interval_minutes)
    if age.total_seconds() >= SYNC_CRITICAL_HOURS * 3600:
        return Check(
            "ad_sync",
            CRITICAL,
            f"letzter vollständiger Abgleich vor {minutes / 60:.0f} Stunden — "
            "neue Konten kommen nicht an, ausgetretene stehen noch in den Listen",
        )
    if minutes >= SYNC_MISSED_WARNING * max(interval, 1):
        return Check(
            "ad_sync",
            WARNING,
            f"letzter vollständiger Abgleich vor {minutes:.0f} Minuten "
            f"(Intervall {interval} Minuten)",
        )
    return Check("ad_sync", OK, f"vor {minutes:.0f} Minuten")


async def _database_checks(
    tenant: Tenant,
    settings: Settings,
    registry: TenantRegistry,
    session_factory: SessionFactoryFor,
) -> list[Check]:
    """Datenbank, Scope und Abgleichsalter — in **einer** Sitzung.

    Die Verbindung als Mandantenrolle mit gesetztem `search_path` ist die
    eigentliche Prüfung: sie beweist DSN, Anmeldung, Schema und die
    Zusicherung aus ADR-0013 D1 in einem Schritt. Eine Sonde, die nur
    `SELECT 1` auf der Prozessverbindung macht, hätte all das nicht geprüft.
    """
    keys = resolve_tenant_keys(
        tenant.slug,
        fallback_audit_key=settings.audit_key.get_secret_value(),
        fallback_audit_key_id=settings.audit_key_id,
        fallback_secrets_key=settings.secrets_key.get_secret_value(),
        single_tenant=len(registry.tenants) == 1,
    )
    sm = session_factory(tenant)
    async with sm() as session:
        attach_keys(session, keys)
        await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
        await session.execute(text("SELECT 1"))
        state = (await session.execute(select(AdSyncState).limit(1))).scalar_one_or_none()
        await session.rollback()
    return [
        Check("database", OK, f"erreichbar als {tenant.db_role or 'Verbindungsrolle'}"),
        _sync_check(state, settings),
    ]


async def stack_health(
    host: str | None,
    *,
    settings: Settings,
    registry: TenantRegistry,
    session_factory: SessionFactoryFor = _default_session_factory,
) -> StackHealth:
    """Den Zustand der Seite unter *host* bestimmen. Wirft nicht."""
    tenant = registry.resolve_host(host)
    if tenant is None:
        return StackHealth(
            None,
            CRITICAL,
            [Check("registry", CRITICAL, f"kein Mandant für Hostname {host!r}")],
        )

    checks = [
        Check("registry", OK, f"Mandant {tenant.slug}"),
        _status_check(tenant),
        _schema_check(tenant),
        _key_check(tenant, registry, settings),
    ]
    if any(c.name == "tenant_key" and c.status == CRITICAL for c in checks):
        # Ohne Schlüssel keine Sitzung: `attach_keys` scheiterte, und der
        # Fehler stünde dann zweimal da — einmal als Ursache, einmal als
        # Folge.
        return StackHealth(tenant.slug, CRITICAL, checks)
    try:
        checks.extend(await _database_checks(tenant, settings, registry, session_factory))
    except Exception as exc:
        # Die Meldung geht an die Überwachung des Betreibers, nicht an einen
        # Anwender. Sie darf deshalb sagen, was los ist — aber der Text kommt
        # aus dem Treiber und kann einen DSN enthalten, also nur die Klasse.
        logger.warning("Stack-Prüfung für %s: Datenbank nicht erreichbar: %s", tenant.slug, exc)
        checks.append(Check("database", CRITICAL, f"nicht erreichbar ({type(exc).__name__})"))

    worst = max(c.status for c in checks)
    return StackHealth(tenant.slug, worst, checks)


__all__ = [
    "CRITICAL",
    "require_health_token",
    "OK",
    "WARNING",
    "Check",
    "StackHealth",
    "stack_health",
]
