"""Welche Art Sicherung heute fällig ist (Entscheid E15).

Zehn Tage Aufbewahrung (E14) decken zwei Fälle **nicht** ab, und beide sind bei
Schulen realistisch:

* Ein Fehler, der erst nach Wochen auffällt — eine verunglückte
  Klassen-Promotion, ein misslungener Import, ein gelöschter Standort. Bei
  Schulen fällt so etwas am Quartalsende auf, nicht am nächsten Tag.
* Ein Verschlüsselungstrojaner sitzt typischerweise **Wochen** im Netz, bevor
  er zuschlägt. Sind alle Sicherungen aus dieser Zeit, ist auch die letzte
  saubere Kopie weg.

Deshalb zwölf Monatskopien. Zwei Festlegungen dazu, die den Unterschied
machen:

**Es wird kein zweiter Dump gezogen.** Die erste geglückte Sicherung eines
Kalendermonats wird *als* Monatskopie geschrieben — derselbe Dump, nur mit
längerer Frist. Ein zusätzlicher Lauf am Monatsersten wäre doppelte Last für
dieselben Daten und ein zweiter Weg, auf dem etwas schiefgehen kann.

**Gezählt wird, nicht datiert.** „Die letzten zwölf" ist ohne
Monatsarithmetik ausdrückbar, hat keine Kanten am 31. und trifft die Zusage
genauer als 365 Tage. Der Aufräumjob auf dem Fileserver kann es mit
``ls | tail`` umsetzen.

**Fällt die Monatskopie aus, wird sie nachgeholt.** Entschieden wird nicht „ist
heute der Erste", sondern „gibt es für diesen Monat schon eine". Scheitert die
Sicherung am 1., wird die vom 2. zur Monatskopie. Ein Monat ohne Kopie wäre
eine Lücke, die niemandem auffällt, bis sie gebraucht wird.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models import BackupKind, BackupStatus, TenantBackup, TenantBackupPolicy

logger = logging.getLogger(__name__)

#: Zustände, die als „es gibt eine Monatskopie" gelten. ``running`` zählt
#: **nicht**: ein Lauf, der noch nicht fertig ist, kann scheitern, und dann
#: hätte der Monat keine Kopie und niemand würde es nachholen.
COUNTS_AS_PRESENT = (BackupStatus.written, BackupStatus.verified)


async def monthly_exists(
    session: AsyncSession, tenant_id: object, *, now: datetime | None = None
) -> bool:
    """Gibt es für den laufenden Kalendermonat schon eine Monatskopie?

    Kalendermonat und nicht „letzte 30 Tage": die Zusage lautet „Stand vom
    Anfang jedes der letzten zwölf Monate", und dafür muss je Monat genau eine
    Kopie existieren.
    """
    moment = now or datetime.now(UTC)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(TenantBackup.id)
        .where(TenantBackup.tenant_id == tenant_id)
        .where(TenantBackup.kind == BackupKind.monthly)
        .where(TenantBackup.status.in_(COUNTS_AS_PRESENT))
        .where(TenantBackup.started_at >= start)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def resolve_kind(
    requested: BackupKind,
    *,
    policy: TenantBackupPolicy | None,
    monthly_present: bool,
) -> BackupKind:
    """Die Art, mit der tatsächlich geschrieben wird.

    Nur eine **tägliche** Sicherung wird befördert. Eine ``manual`` bleibt
    manuell (sonst hätte ein Handgriff plötzlich eine Zwölfmonatsfrist), eine
    ``pre_migration`` bleibt es auch (sie hat ihre eigene Frist aus D6), und
    eine ``offboarding`` erst recht.
    """
    if requested is not BackupKind.daily:
        return requested
    if policy is not None and not policy.monthly_enabled:
        return requested
    if monthly_present:
        return requested
    return BackupKind.monthly


def keep_for(kind: BackupKind, policy: TenantBackupPolicy | None) -> str:
    """Aufbewahrung einer Art, als Text für Protokoll und Auskunft."""
    retention = policy.retention_days if policy else 10
    pre_migration = policy.pre_migration_retention_days if policy else 30
    keep = policy.monthly_keep if policy else 12
    if kind is BackupKind.monthly:
        return f"die letzten {keep} Monatskopien"
    if kind is BackupKind.pre_migration:
        return f"{pre_migration} Tage"
    return f"{retention} Tage"


__all__ = ["COUNTS_AS_PRESENT", "keep_for", "monthly_exists", "resolve_kind"]
