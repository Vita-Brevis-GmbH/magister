"""Tägliche Sicherung aller aktiven Kunden (ADR-0024 D6).

Vorher war die tägliche Sicherung eine Cron-Zeile im Runbook — auf einem Host,
auf dem niemand sie eingetragen hatte, gab es sie nicht. Jetzt läuft sie in
der Konsole selbst: einmal am Tag zur Uhrzeit ``COCKPIT_BACKUP_DAILY_AT``
(UTC), für jeden aktiven Kunden, über denselben Weg wie „Sicherung jetzt"
(:func:`cockpit_api.services.backup_run.perform_backup`).

**Einmal je Tag und Kunde, auch nach einem Neustart.** Entschieden wird an
der Datenbank, nicht an einer Variablen im Speicher: gibt es für den Kunden
seit dem heutigen Zeitpunkt schon eine Sicherung (gleich welcher Art und mit
welchem Ausgang), wird keine weitere gezogen. Ein Neustart um 01:35 zieht
also keine zweite, und eine gescheiterte wird nicht im Minutentakt
wiederholt — sie steht als ``failed`` in der Liste, und das ist der Befund.

Ein Kunde, der stolpert, hält die anderen nicht auf.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time

from sqlalchemy import select, text

from cockpit_api.config import settings
from cockpit_api.db import SessionFactory
from cockpit_api.models import BackupKind, Tenant, TenantBackup, TenantStatus
from cockpit_api.services.backup_run import BackupSetupError, perform_backup

logger = logging.getLogger(__name__)

TICK_SECONDS = 60.0
#: Advisory-Lock, damit zwei Konsolen-Prozesse nicht beide sichern.
_LOCK_KEY = 0x6D61_6762  # "magb"


def parse_daily_at(value: str) -> time | None:
    """``HH:MM`` → Uhrzeit (UTC). Leer oder ungültig → ``None`` (abgeschaltet)."""
    value = value.strip()
    if not value:
        return None
    try:
        hours, minutes = value.split(":", 1)
        return time(int(hours), int(minutes), tzinfo=UTC)
    except ValueError:
        logger.error("COCKPIT_BACKUP_DAILY_AT=%r ist keine Uhrzeit HH:MM — Zeitplaner aus", value)
        return None


def slot_for(now: datetime, at: time) -> datetime | None:
    """Der heutige Zeitpunkt, wenn er schon erreicht ist — sonst ``None``."""
    slot = datetime.combine(now.date(), at.replace(tzinfo=None), tzinfo=UTC)
    return slot if now >= slot else None


async def run_due_backups(now: datetime | None = None) -> int:
    """Alle fälligen Sicherungen ziehen. Gibt zurück, wie viele gezogen wurden."""
    at = parse_daily_at(settings.backup_daily_at)
    if at is None:
        return 0
    current = now or datetime.now(UTC)
    slot = slot_for(current, at)
    if slot is None:
        return 0
    done = 0
    async with SessionFactory() as session:
        got = (
            await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY})
        ).scalar()
        if not got:
            return 0
        try:
            tenants = (
                (
                    await session.execute(
                        select(Tenant)
                        .where(Tenant.status == TenantStatus.active)
                        .order_by(Tenant.slug)
                    )
                )
                .scalars()
                .all()
            )
            for tenant in tenants:
                already = (
                    await session.execute(
                        select(TenantBackup.id)
                        .where(TenantBackup.tenant_id == tenant.id)
                        .where(TenantBackup.started_at >= slot)
                        .limit(1)
                    )
                ).first()
                if already is not None:
                    continue
                try:
                    row = await perform_backup(session, tenant, BackupKind.daily)
                except BackupSetupError as exc:
                    # Nicht eingerichtet: für alle Kunden gleich, also einmal
                    # melden und die Runde beenden.
                    logger.warning("Tägliche Sicherung nicht möglich: %s", exc)
                    return done
                except Exception:
                    logger.exception("Tägliche Sicherung für %s gescheitert", tenant.slug)
                    await session.rollback()
                    continue
                done += 1
                logger.info("Tägliche Sicherung für %s: %s", tenant.slug, row.status.value)
        finally:
            await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            await session.commit()
    return done


async def backup_scheduler_loop() -> None:
    if parse_daily_at(settings.backup_daily_at) is None:
        logger.info("Tägliche Sicherung abgeschaltet (COCKPIT_BACKUP_DAILY_AT leer)")
        return
    logger.info("Tägliche Sicherung um %s UTC eingeplant", settings.backup_daily_at)
    while True:
        # Erst warten, dann prüfen: ein Start (oder ein Test, der die
        # Anwendung kurz hochfährt) soll nicht als Erstes pg_dump starten.
        await asyncio.sleep(TICK_SECONDS)
        try:
            await run_due_backups()
        except Exception:
            logger.exception("Runde des Sicherungs-Zeitplaners gescheitert")


__all__ = [
    "backup_scheduler_loop",
    "parse_daily_at",
    "run_due_backups",
    "slot_for",
]
