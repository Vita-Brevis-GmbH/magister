"""Den echten Schemastand an die Konsole melden (ADR-0021 D2).

Bisher ging alles in eine Richtung: die Datenebene **zieht** (ADR-0013 D4).
Das bleibt der Normalfall — dies ist die eine Ausnahme, und sie hat einen
Grund, der in der Konsole nicht zu beheben ist.

`tenants.schema_version` in der Konsolen-Datenbank trägt bis hierher den Wert
aus `COCKPIT_EXPECTED_SCHEMA_VERSION`, also **was die Konsole erwartet hat**,
nicht was Alembic erreicht hat. Genau diese Spalte fährt aber die
Versions-Schranke (ADR-0013 D7): weicht sie vom Schema ab, hält die Schranke
entweder einen gesunden Kunden zurück oder — schlimmer — lässt einen durch,
dessen Schema hinterherhängt. Die Konsole kann das nicht selbst richtigstellen:
sie hat keinen Datenbankzugang zum Kunden, und das bleibt so.

Also meldet die Stelle, die migriert hat, was dabei herauskam.

Was diese Meldung **nicht** trägt: Personendaten, Schlüssel, DSNs. Nur die
Revision und der Zeitpunkt. Und sie ist idempotent — dieselbe Revision
zweimal gemeldet ändert nichts.

**Eine gescheiterte Meldung ist kein gescheiterter Rollout.** Die Migration
ist gelaufen; nur die Konsole weiss es noch nicht. Deshalb eine Warnung und
kein Abbruch — sonst sähe eine geglückte Migration mit unerreichbarer Konsole
wie eine gescheiterte aus. Dieselbe Regel wie bei der Backup-Meldung
(`cockpit_api/cli/_report.py`).
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ReportRejectedError(RuntimeError):
    """Die Konsole hat die Meldung nicht angenommen. Kein Grund abzubrechen."""


def console_base(console_url: str) -> str:
    """Basis-Adresse aus der Registry-Adresse ableiten.

    Wie in `desired_state.fetch_desired_state`: eine zweite Einstellung für
    dieselbe Konsole wäre eine, die mit der ersten auseinanderläuft.
    """
    base = console_url.rstrip("/")
    if base.endswith("/tenants/registry"):
        base = base[: -len("/tenants/registry")]
    return base


async def read_schema_head(session: AsyncSession, schema_name: str) -> str | None:
    """Die Revision, die **im Schema** steht. `None`, wenn es sie nicht gibt.

    Gefragt wird `alembic_version` in genau diesem Schema — jeder Mandant hat
    seine eigene (ADR-0013 D7), eine gemeinsame würde die Migration eines
    Kunden wie die von allen aussehen lassen.

    `None` heisst nicht „Fehler", sondern „nie über Alembic migriert": eine
    Testumgebung, die ihr Schema mit `create_all` baut, hat die Tabelle nicht.
    Der Aufrufer meldet dann nichts, statt eine Unwahrheit zu melden.

    Das Schema kommt aus der Registry und ist dort schon geprüft; hier steht
    es als Bind-Parameter und nicht im Statement-Text, obwohl `to_regclass`
    einen Text erwartet — damit ein Wert aus einer manipulierten Registry
    nicht in SQL landet.
    """
    exists = (
        await session.execute(
            text("SELECT to_regclass(:qualified)"), {"qualified": f"{schema_name}.alembic_version"}
        )
    ).scalar()
    if exists is None:
        return None
    row = (
        await session.execute(
            text(  # noqa: S608 — der Name ist oben über to_regclass geprüft
                f'SELECT version_num FROM "{schema_name}".alembic_version LIMIT 1'
            )
        )
    ).scalar_one_or_none()
    return str(row) if row else None


async def report_schema_version(
    console_url: str,
    tenant_console_id: str,
    *,
    head_revision: str,
    token: str,
    management_marker: str = "",
    timeout_s: float = 5.0,
) -> None:
    """Den Stand melden. Wirft :class:`ReportRejectedError`, wenn es nicht ankam."""
    url = f"{console_base(console_url)}/tenants/{tenant_console_id}/schema-version"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if management_marker:
        headers["X-Magister-Management"] = management_marker
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                url, headers=headers, json={"head_revision": head_revision}
            )
    except httpx.HTTPError as exc:
        raise ReportRejectedError(f"Konsole nicht erreichbar: {exc}") from exc
    if response.status_code not in (200, 204):
        # Kein Token und kein Antwortkörper im Text: das geht in den Log.
        raise ReportRejectedError(
            f"Konsole antwortete mit HTTP {response.status_code} auf die Standmeldung."
        )


__all__ = [
    "ReportRejectedError",
    "console_base",
    "read_schema_head",
    "report_schema_version",
]
