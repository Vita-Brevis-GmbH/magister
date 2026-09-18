"""Offboarding mit Fristen (ADR-0016 D8).

Der Ablauf ist eine Kette von Schritten mit **Reihenfolgeschranken**, und die
Schranken sind der eigentliche Inhalt dieses Moduls. Jede einzelne verhindert
einen Schaden, den man nicht zurücknehmen kann:

* **Nichts wird gelöscht, bevor der Export beim Kunden ist.** Die andere
  Reihenfolge wäre der Fall, in dem ein Kunde nach dem Anbieterwechsel nach
  seinen Daten fragt und wir sie nicht mehr haben. Sein Recht auf Herausgabe
  (nDSG, DSGVO Art. 20) endet nicht mit der Kündigung.
* **Nichts wird vor Ablauf der Karenzzeit gelöscht.** 30 Tage sind der
  Vertragswert; sie sind da, damit ein Nachtrag noch möglich ist, wenn die
  zuständige Person Ferien hat.
* **Löschen verlangt zwei Personen.** Wie das Umschalten einer
  Wiederherstellung (D5), und aus dem stärkeren Grund: ein ``DROP SCHEMA`` auf
  ein Kundenschema ist die unwiderruflichste Operation im System.
* **Der Kundenschlüssel wird bestätigt, nicht geprüft.** Die Konsole kann ihn
  nicht vernichten — er liegt in der Umgebung des Anwendungsservers. Sie hält
  fest, dass ein Mensch es getan hat. Diese Grenze steht hier, weil ein Feld
  namens ``key_destroyed_at`` sonst wie ein Nachweis aussieht.

Was das Modul **nicht** tut: Sicherungen löschen. Auf dem Share hat die
Konsole keine Löschrechte (ADR-0016 D2), und das ist Absicht. Die Sicherungen
laufen über die Aufbewahrungsfrist ab; ``purge_due_at`` ist das Datum, das dem
Kunden zugesagt wird — nicht der Zeitpunkt, an dem jemand etwas tut.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from cockpit_api.models import (
    ExportJob,
    ExportState,
    OffboardingState,
    Tenant,
    TenantBackupPolicy,
    TenantOffboarding,
    TenantStatus,
)
from cockpit_api.services.provisioning import IDENTIFIER_PATTERN

logger = logging.getLogger(__name__)

#: Zustände, aus denen ein Offboarding beginnen darf.
STARTABLE = (TenantStatus.active, TenantStatus.suspended)

#: Zustände, in denen noch nichts gelöscht ist und ein Widerruf möglich bleibt.
ABORTABLE = (OffboardingState.requested, OffboardingState.export_ready)


class OffboardingError(RuntimeError):
    """Ein Schritt ist in dieser Reihenfolge nicht zulässig."""


def _ident(value: str, *, field: str) -> str:
    if not IDENTIFIER_PATTERN.match(value):
        raise OffboardingError(f"{field}={value!r} ist kein zulässiger Bezeichner.")
    return f'"{value}"'


async def start(
    session: AsyncSession,
    tenant: Tenant,
    *,
    reason: str,
    requested_by: str,
    grace_days: int | None = None,
    now: datetime | None = None,
) -> TenantOffboarding:
    """Kündigung erfassen. Der Kunde wird sofort nicht mehr bedient.

    ``status = offboarding`` heisst in der Datenebene 503 (ADR-0013 D3): in
    einem Übergang, in dem Daten wandern, liest oder schreibt eine Anfrage
    einen halben Zustand. Der Export läuft trotzdem — er geht nicht über den
    Anfragepfad, sondern direkt gegen das Schema.
    """
    if not reason.strip():
        raise OffboardingError("Ein Offboarding ohne benannten Anlass wird nicht erfasst.")
    if tenant.status not in STARTABLE:
        raise OffboardingError(
            f"Kunde {tenant.slug} ist {tenant.status.value}; ein Offboarding beginnt "
            "aus active oder suspended."
        )
    existing = await session.get(TenantOffboarding, tenant.id)
    if existing is not None and existing.state is not OffboardingState.aborted:
        raise OffboardingError(f"Für {tenant.slug} läuft bereits ein Offboarding.")

    moment = now or datetime.now(UTC)
    days = grace_days if grace_days is not None else 30
    if days < 0:
        raise OffboardingError("Eine negative Karenzzeit gibt es nicht.")
    row = existing or TenantOffboarding(tenant_id=tenant.id)
    row.state = OffboardingState.requested
    row.reason = reason.strip()
    row.requested_by = requested_by
    row.requested_at = moment
    row.grace_days = days
    row.grace_until = moment + timedelta(days=days)
    row.aborted_at = None
    row.aborted_reason = None
    session.add(row)
    tenant.status = TenantStatus.offboarding
    await session.flush()
    logger.info(
        "Offboarding für %s erfasst, Karenzzeit bis %s", tenant.slug, row.grace_until.isoformat()
    )
    return row


async def record_export(
    session: AsyncSession,
    row: TenantOffboarding,
    export: ExportJob,
    *,
    now: datetime | None = None,
) -> TenantOffboarding:
    """Den zugestellten Export vermerken.

    Verlangt einen Export, der **fertig** ist. Ein bestellter, aber
    gescheiterter Export würde sonst die Löschsperre aufheben, ohne dass der
    Kunde etwas in der Hand hat.
    """
    if export.tenant_id != row.tenant_id:
        raise OffboardingError("Der Export gehört zu einem anderen Kunden.")
    if export.state not in (ExportState.ready, ExportState.downloaded):
        raise OffboardingError(
            f"Der Export ist {export.state.value}. Vermerkt wird nur ein fertiger — "
            "sonst hebt ein gescheiterter Export die Löschsperre auf."
        )
    row.export_job_id = export.id
    row.export_delivered_at = now or datetime.now(UTC)
    row.state = OffboardingState.export_ready
    await session.flush()
    return row


async def drop_data(
    session: AsyncSession,
    tenant: Tenant,
    row: TenantOffboarding,
    *,
    engine: AsyncEngine,
    dropped_by: str,
    approved_by: str,
    now: datetime | None = None,
) -> TenantOffboarding:
    """Schema und Datenbankrolle löschen. Unwiderruflich.

    Vier Schranken davor, und keine davon ist überflüssig:

    1. Der Export muss zugestellt sein.
    2. Die Karenzzeit muss abgelaufen sein.
    3. Zwei **verschiedene** Personen.
    4. Der Kunde muss im Offboarding sein — nicht aktiv.
    """
    moment = now or datetime.now(UTC)
    if row.state is OffboardingState.aborted:
        raise OffboardingError("Das Offboarding wurde widerrufen.")
    if row.dropped_at is not None:
        # Idempotent: ein zweiter Aufruf ist kein Fehler, aber er löscht auch
        # nichts noch einmal.
        return row
    if row.export_delivered_at is None:
        raise OffboardingError(
            "Es ist kein zugestellter Export vermerkt. Das Recht des Kunden auf "
            "Herausgabe seiner Daten endet nicht mit der Kündigung."
        )
    if moment < row.grace_until:
        raise OffboardingError(
            f"Die Karenzzeit läuft bis {row.grace_until.isoformat()}. Vorher wird nichts gelöscht."
        )
    if not dropped_by.strip() or not approved_by.strip():
        raise OffboardingError("Löschen verlangt zwei benannte Personen.")
    if dropped_by.strip().lower() == approved_by.strip().lower():
        raise OffboardingError(
            "Ausführende und freigebende Person müssen verschieden sein. Ein "
            "DROP SCHEMA auf ein Kundenschema ist die unwiderruflichste "
            "Operation im System."
        )
    if tenant.status is not TenantStatus.offboarding:
        raise OffboardingError(f"Kunde {tenant.slug} ist {tenant.status.value}, nicht offboarding.")

    schema = _ident(tenant.schema_name, field="schema_name")
    role = _ident(tenant.db_role, field="db_role")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        # Die Rolle kann noch Rechte in anderen Objekten halten; ohne
        # REASSIGN/DROP OWNED scheitert DROP ROLE mit "cannot be dropped
        # because some objects depend on it".
        await conn.exec_driver_sql(f"DROP OWNED BY {role} CASCADE")
        await conn.exec_driver_sql(f"DROP ROLE IF EXISTS {role}")
    async with engine.connect() as conn:
        left = (
            await conn.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": tenant.schema_name},
            )
        ).scalar()
        role_left = (
            await conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": tenant.db_role}
            )
        ).scalar()
    if left or role_left:
        raise OffboardingError(
            f"Nach dem Löschen existieren noch: "
            f"{'Schema ' if left else ''}{'Rolle' if role_left else ''}. "
            "Der Zustand wird nicht als gelöscht vermerkt."
        )

    row.dropped_at = moment
    row.dropped_by = dropped_by.strip()
    row.approved_by = approved_by.strip()
    row.key_id = tenant.audit_key_id
    row.state = OffboardingState.dropped
    await session.flush()
    logger.info(
        "Schema %s und Rolle %s gelöscht (%s, freigegeben von %s)",
        tenant.schema_name,
        tenant.db_role,
        row.dropped_by,
        row.approved_by,
    )
    return row


async def confirm_key_destroyed(
    session: AsyncSession,
    row: TenantOffboarding,
    *,
    confirmed_by: str,
    retention_days: int | None = None,
    now: datetime | None = None,
) -> TenantOffboarding:
    """Vernichtung des Kundenschlüssels festhalten (Crypto-Shredding).

    **Festhalten, nicht prüfen.** Der Schlüssel steht in der Umgebung des
    Anwendungsservers (``MAGISTER_TENANT_AUDIT_KEY_<REF>``); die Konsole kommt
    nicht dorthin. Was sie tun kann, ist den Vorgang dokumentieren und daraus
    die Frist berechnen, die dem Kunden zugesagt wird. Wer hier bestätigt,
    bestätigt eine Handlung, die er selbst ausgeführt hat.

    Ab hier gilt: die Audit-Payloads und gespeicherten Passwörter dieses
    Kunden sind unlesbar — auch in jeder bereits geschriebenen Sicherung. Der
    Rest (Namen, Klassen, Zuordnungen) läuft mit ``purge_due_at`` ab.
    """
    if row.dropped_at is None:
        raise OffboardingError(
            "Erst Schema und Rolle löschen. Ein vernichteter Schlüssel bei "
            "laufendem Betrieb hiesse: der Kunde ist online und kann nichts "
            "mehr schreiben."
        )
    if not confirmed_by.strip():
        raise OffboardingError("Die Bestätigung braucht einen Namen.")
    moment = now or datetime.now(UTC)
    days = retention_days if retention_days is not None else 10
    row.key_destroyed_at = moment
    row.key_destroyed_by = confirmed_by.strip()
    row.purge_due_at = moment + timedelta(days=days)
    row.state = OffboardingState.shredded
    await session.flush()
    logger.info(
        "Kundenschlüssel %s als vernichtet vermerkt (%s); Sicherungen laufen ab %s",
        row.key_id or "?",
        row.key_destroyed_by,
        row.purge_due_at.isoformat(),
    )
    return row


async def mark_purged(
    session: AsyncSession, row: TenantOffboarding, *, now: datetime | None = None
) -> TenantOffboarding:
    """Fristablauf vermerken — erst wenn er wirklich eingetreten ist.

    Kein Handgriff, sondern ein Datum: ab hier sind auch die Sicherungen auf
    dem Share und im Tages-Backup abgelaufen, und die Löschzusage ist erfüllt.
    Vorher „vollständig gelöscht" zu melden, wäre unwahr.
    """
    if row.purge_due_at is None:
        raise OffboardingError("Ohne vernichteten Kundenschlüssel gibt es keine Frist.")
    moment = now or datetime.now(UTC)
    if moment < row.purge_due_at:
        raise OffboardingError(
            f"Die Aufbewahrungsfrist läuft bis {row.purge_due_at.isoformat()}. "
            "Bis dahin existieren die Sicherungen, und das ist dem Kunden so zugesagt."
        )
    row.purged_at = moment
    row.state = OffboardingState.purged
    await session.flush()
    return row


async def abort(
    session: AsyncSession,
    tenant: Tenant,
    row: TenantOffboarding,
    *,
    reason: str,
    restore_status: TenantStatus = TenantStatus.active,
    now: datetime | None = None,
) -> TenantOffboarding:
    """Kündigung zurückziehen. Nur solange nichts gelöscht ist."""
    if row.state not in ABORTABLE:
        raise OffboardingError(
            f"Ein Offboarding im Zustand {row.state.value} lässt sich nicht "
            "widerrufen — es ist bereits etwas gelöscht."
        )
    if not reason.strip():
        raise OffboardingError("Ein Widerruf braucht eine Begründung.")
    row.state = OffboardingState.aborted
    row.aborted_at = now or datetime.now(UTC)
    row.aborted_reason = reason.strip()
    tenant.status = restore_status
    await session.flush()
    logger.info("Offboarding für %s widerrufen: %s", tenant.slug, row.aborted_reason)
    return row


async def retention_days_for(session: AsyncSession, tenant: Tenant) -> int:
    """Aufbewahrungsfrist dieses Kunden, sonst der Vorgabewert (E14: 10 Tage)."""
    policy = await session.get(TenantBackupPolicy, tenant.id)
    return policy.retention_days if policy is not None else 10


__all__ = [
    "ABORTABLE",
    "STARTABLE",
    "OffboardingError",
    "abort",
    "confirm_key_destroyed",
    "drop_data",
    "mark_purged",
    "record_export",
    "retention_days_for",
    "start",
]
