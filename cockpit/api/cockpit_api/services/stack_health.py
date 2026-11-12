"""Tiefer Gesundheitszustand der Konsole — für die Überwachung.

`/api/health` sagt „der Prozess lebt". Für den Betreiber ist das zu wenig: die
Konsole lebt auch dann, wenn ihre Datenbank weg ist, die Connector-CA in zehn
Tagen abläuft oder die halbe Agentenflotte still ist.

Dieselben Stufen wie überall sonst (ADR-0021 D6): 0 in Ordnung, 1 Warnung,
2 kritisch. Die Flotten-Befunde werden **nicht** noch einmal gerechnet,
sondern aus `services/fleet` übernommen — zwei Stellen, die denselben
Schweregrad bestimmen, bestimmen ihn eines Tages verschieden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.config import settings
from cockpit_api.models import JobStatus, ProvisioningJob, Tenant, TenantStatus
from cockpit_api.services.fleet import Severity, exit_code, fleet_findings

logger = logging.getLogger(__name__)

OK = 0
WARNING = 1
CRITICAL = 2

STATE_NAMES = {OK: "ok", WARNING: "warning", CRITICAL: "critical"}

#: Die Connector-CA signiert die Agentenzertifikate. Läuft sie ab, kommt kein
#: Agent mehr herein — und keiner kann sich erneuern. Vier Wochen Vorlauf,
#: damit eine Erneuerung in ein Wartungsfenster passt und nicht in eine Nacht.
CA_WARNING_DAYS = 28
CA_CRITICAL_DAYS = 7


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: int
    detail: str


@dataclass(frozen=True, slots=True)
class StackHealth:
    status: int
    checks: list[Check]

    @property
    def state(self) -> str:
        return STATE_NAMES[self.status]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "state": self.state,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks
            ],
        }


def _certificate_check() -> Check:
    """Restlaufzeit der Connector-CA.

    Gelesen wird die Datei, nicht die Datenbank: was zählt, ist das
    Zertifikat, mit dem dieser Prozess **gerade** signiert. Ein Eintrag
    irgendwo daneben könnte von einer früheren Fassung stammen.
    """
    path = settings.connector_ca_cert
    if not path:
        return Check("connector_ca", WARNING, "keine Connector-CA konfiguriert")
    try:
        cert = x509.load_pem_x509_certificate(Path(path).read_bytes())
    except Exception as exc:
        return Check("connector_ca", CRITICAL, f"nicht lesbar ({type(exc).__name__})")
    days = (cert.not_valid_after_utc - datetime.now(UTC)).days
    if days < 0:
        return Check("connector_ca", CRITICAL, f"seit {abs(days)} Tag(en) abgelaufen")
    if days <= CA_CRITICAL_DAYS:
        return Check("connector_ca", CRITICAL, f"läuft in {days} Tag(en) ab")
    if days <= CA_WARNING_DAYS:
        return Check("connector_ca", WARNING, f"läuft in {days} Tag(en) ab")
    return Check("connector_ca", OK, f"gültig noch {days} Tage")


async def _database_check(session: AsyncSession) -> list[Check]:
    total = int((await session.execute(select(func.count()).select_from(Tenant))).scalar_one() or 0)
    stuck = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Tenant)
                .where(Tenant.status == TenantStatus.provisioning)
            )
        ).scalar_one()
        or 0
    )
    failed = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ProvisioningJob)
                .where(ProvisioningJob.status == JobStatus.failed)
            )
        ).scalar_one()
        or 0
    )
    checks = [Check("database", OK, f"erreichbar, {total} Kunde(n)")]
    if stuck:
        # Ein Kunde in `provisioning` ist nicht erreichbar. Das ist während
        # einer Einrichtung normal und nach einer Stunde ein Befund — die
        # Unterscheidung trifft der Mensch, deshalb Warnung und nicht
        # kritisch.
        checks.append(
            Check("provisioning", WARNING, f"{stuck} Kunde(n) in Bereitstellung — nicht erreichbar")
        )
    if failed:
        checks.append(
            Check("provisioning_jobs", WARNING, f"{failed} abgebrochene(r) Bereitstellungsauftrag")
        )
    return checks


async def _fleet_check(session: AsyncSession) -> Check:
    found = await fleet_findings(session)
    code = exit_code(found)
    if not found:
        return Check("fleet", OK, "keine Befunde")
    worst = [f for f in found if f.severity is Severity.critical]
    return Check(
        "fleet",
        code,
        f"{len(worst)} kritisch, {len(found) - len(worst)} Warnung(en) — "
        "Einzelheiten unter /api/fleet/findings",
    )


async def stack_health(session: AsyncSession) -> StackHealth:
    """Zustand der Konsole. Wirft nicht — eine Sonde, die wirft, sagt nichts."""
    checks: list[Check] = []
    try:
        checks.extend(await _database_check(session))
    except Exception as exc:
        logger.warning("Stack-Prüfung: Konsolen-Datenbank nicht erreichbar: %s", exc)
        return StackHealth(
            CRITICAL, [Check("database", CRITICAL, f"nicht erreichbar ({type(exc).__name__})")]
        )
    checks.append(_certificate_check())
    try:
        checks.append(await _fleet_check(session))
    except Exception as exc:
        logger.warning("Stack-Prüfung: Flotten-Befunde nicht berechenbar: %s", exc)
        checks.append(Check("fleet", WARNING, f"nicht berechenbar ({type(exc).__name__})"))
    return StackHealth(max(c.status for c in checks), checks)


__all__ = ["CRITICAL", "OK", "WARNING", "Check", "StackHealth", "stack_health"]
