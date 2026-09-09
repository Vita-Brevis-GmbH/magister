"""Auftragswarteschlange für die Connector-Agenten (ADR-0014).

Die Plattform legt Aufträge ab, der Agent holt sie mit einem Long-Poll und
liefert Ergebnisse zurück. Es gibt keine Verbindung von der Plattform ins
Kundennetz — nur diesen Anruf von innen nach aussen.

Drei Grenzen, die nicht verhandelbar sind:

**Die Methodenmenge ist eine Allowlist**, wörtlich die aus
``magister_api.ad.rpc.ALLOWED_METHODS``. Es gibt keinen Weg, beliebiges LDAP,
PowerShell oder ein Skript zu schicken — auch nicht für einen Global Admin.
Ein Auftrag mit einer anderen Methode wird schon beim Einstellen verweigert,
nicht erst im Agenten.

**Aufträge verfallen.** Ein Agent, der zehn Minuten weg war, soll ein Passwort
nicht mehr setzen: der Anwender hat längst einen Fehler gesehen und es erneut
versucht. Ein spät ausgeführter Auftrag setzte dann das *alte* Passwort.

**Nutzlasten mit Passwörtern werden nach Abschluss gelöscht.**
``payload_purged_at`` hält fest, dass ein leeres Feld absichtlich leer ist und
nicht nie gefüllt war.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models import ConnectorAgent, ConnectorJob, JobState, Tenant

logger = logging.getLogger(__name__)

#: Wörtlich die Allowlist der Datenebene (``magister_api/ad/rpc.py``). Bewusst
#: hier wiederholt und nicht importiert: die Konsole ist eine eigene Anwendung
#: mit eigenen Abhängigkeiten und kann ``magister_api`` nicht importieren. Ein
#: Test hält die beiden Mengen zusammen.
ALLOWED_METHODS: frozenset[str] = frozenset(
    {
        "find_user_dn",
        "fetch_user_groups",
        "probe_service_connection",
        "probe_service_connection_detailed",
        "probe_bind_as_user",
        "modify_password",
        "modify_user_attributes",
        "rename_user",
        "set_proxy_addresses",
        "set_account_enabled",
        "set_password_never_expires",
        "set_cannot_change_password",
        "delete_user_object",
        "add_user_to_groups",
        "remove_user_from_groups",
        "create_user",
    }
)

#: Methoden, deren Nutzlast ein Passwort trägt. Deren ``payload`` wird nach
#: Abschluss sofort gelöscht.
PASSWORD_BEARING_METHODS: frozenset[str] = frozenset(
    {"modify_password", "probe_bind_as_user", "create_user"}
)

#: Standard-Lebensdauer eines Auftrags.
JOB_TTL = timedelta(seconds=90)


class MethodNotAllowedError(RuntimeError):
    """Die Methode steht nicht in der Allowlist."""


class JobNotClaimableError(RuntimeError):
    """Der Auftrag gehört nicht diesem Agenten oder ist nicht mehr offen."""


async def enqueue(
    session: AsyncSession,
    tenant: Tenant,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    ttl: timedelta = JOB_TTL,
) -> ConnectorJob:
    if method not in ALLOWED_METHODS:
        # Verweigerung schon hier, nicht erst im Agenten: die erste Grenze
        # gehört dorthin, wo der Auftrag entsteht.
        raise MethodNotAllowedError(
            f"Methode {method!r} steht nicht in der Allowlist. Der Connector führt "
            "ausschliesslich die bekannten AD-Operationen aus — kein freies LDAP, "
            "kein PowerShell, keine Skripte."
        )
    job = ConnectorJob(
        tenant_id=tenant.id,
        method=method,
        payload=payload,
        expires_at=datetime.now(UTC) + ttl,
    )
    session.add(job)
    await session.flush()
    # Kein payload im Log: er kann ein Passwort enthalten.
    logger.info("Auftrag %s (%s) für Kunde %s eingestellt", job.id, method, tenant.slug)
    return job


async def expire_stale_jobs(session: AsyncSession, tenant_id: UUID) -> int:
    """Verfallene Aufträge markieren, bevor abgeholt wird.

    Getrennter Schritt und kein Filter beim Abholen: ein Auftrag, der verfällt,
    soll als ``expired`` sichtbar sein und nicht einfach nie wieder auftauchen.
    Der Aufrufer in der Datenebene wartet auf ein Ergebnis — ihm muss man sagen
    können, dass keines mehr kommt.
    """
    now = datetime.now(UTC)
    result = await session.execute(
        update(ConnectorJob)
        .where(
            ConnectorJob.tenant_id == tenant_id,
            ConnectorJob.state.in_([JobState.queued, JobState.claimed]),
            ConnectorJob.expires_at <= now,
        )
        .values(state=JobState.expired, finished_at=now, payload=None, payload_purged_at=now)
        .returning(ConnectorJob.id)
    )
    expired = list(result.scalars())
    if expired:
        logger.info("%d Auftrag/Aufträge verfallen (Kunde %s)", len(expired), tenant_id)
    return len(expired)


async def claim_next(
    session: AsyncSession, agent: ConnectorAgent, *, limit: int = 1
) -> list[ConnectorJob]:
    """Offene Aufträge des eigenen Kunden übernehmen.

    ``FOR UPDATE SKIP LOCKED``: mehrere Agenten desselben Kunden holen sich
    nicht denselben Auftrag, und keiner wartet auf den anderen.
    """
    await expire_stale_jobs(session, agent.tenant_id)
    stmt = (
        select(ConnectorJob)
        .where(
            # tenant_id des AGENTEN, nicht aus der Anfrage: ein Agent kann
            # nicht nach Aufträgen eines anderen Kunden fragen.
            ConnectorJob.tenant_id == agent.tenant_id,
            ConnectorJob.state == JobState.queued,
        )
        .order_by(ConnectorJob.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    jobs = list((await session.execute(stmt)).scalars())
    now = datetime.now(UTC)
    for job in jobs:
        job.state = JobState.claimed
        job.agent_id = agent.id
        job.claimed_at = now
        job.attempts += 1
    await session.flush()
    return jobs


async def submit_result(
    session: AsyncSession,
    agent: ConnectorAgent,
    job_id: UUID,
    *,
    ok: bool,
    result: Any,
    error: str | None,
) -> ConnectorJob:
    job = await session.get(ConnectorJob, job_id)
    if job is None:
        raise JobNotClaimableError("Unbekannter Auftrag.")
    if job.tenant_id != agent.tenant_id:
        # Der Agent von Kunde A darf kein Ergebnis für Kunde B abliefern.
        logger.warning("Agent %s wollte ein Ergebnis für einen fremden Kunden abliefern", agent.id)
        raise JobNotClaimableError("Auftrag gehört einem anderen Kunden.")
    if job.state is not JobState.claimed or job.agent_id != agent.id:
        raise JobNotClaimableError(
            f"Auftrag ist im Zustand {job.state.value} und nicht von diesem Agenten übernommen."
        )

    now = datetime.now(UTC)
    job.state = JobState.done if ok else JobState.failed
    job.result = result
    job.error = error
    job.finished_at = now
    if job.method in PASSWORD_BEARING_METHODS or job.payload is not None:
        # Sofort nach Abschluss, nicht per Aufräumlauf: ein Passwort, das noch
        # zehn Minuten in der Datenbank liegt, ist zehn Minuten zu lang.
        job.payload = None
        job.payload_purged_at = now
    await session.flush()
    logger.info("Auftrag %s abgeschlossen: %s", job.id, job.state.value)
    return job
