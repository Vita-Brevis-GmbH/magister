"""Mandanten-Bindung einer Transaktion (ADR-0013 D1).

Pro Transaktion setzt die Anwendung ``SET LOCAL search_path``, prüft danach
nach, dass es angekommen ist, und erst dann läuft der eigentliche Code. Die
Einstellung endet mit der Transaktion, ein Pool kann sie also nicht
weitertragen.

Die Trennung selbst hängt aber **nicht** daran, sondern an der Anmelderolle der
Verbindung: jeder Mandant hat seine eigene, mit entzogenem ``USAGE`` auf jedes
andere Mandantenschema. Damit erzwingt Postgres die Trennung, nicht die
Anwendung — ein vergessener Filter liefert keine fremden Zeilen, sondern einen
Fehler, und auch ein Angreifer mit SQL-Ausführung findet auf dieser Verbindung
keine fremde Rolle, in die er wechseln könnte.

Zum Raw-SQL in diesem Modul: ``SET`` nimmt keine Bind-Parameter, Schema- und
Rollenname müssen als Text ins Statement. Deshalb liegt das hier — unterhalb
des Repository-Layers, in der Sitzungs-Einrichtung — und nicht in einem Router,
und deshalb wird jeder Bezeichner vor dem Einsetzen erneut geprüft, obwohl die
Registry das beim Laden schon getan hat. Zwei Prüfungen an derselben Stelle
sind billiger als eine Lücke.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.tenancy.registry import IDENTIFIER_PATTERN, Tenant

logger = logging.getLogger(__name__)


class TenantScopeError(RuntimeError):
    """Die Transaktion ist nicht dem erwarteten Mandanten zugeordnet.

    Kein Zustand, aus dem man sich erholt: die Anfrage wird abgebrochen, bevor
    eine einzige Zeile gelesen wird.
    """


def quote_identifier(value: str, *, field: str) -> str:
    """Bezeichner für ein ``SET``-Statement — geprüft **und** gequotet.

    Die Prüfung ist die Grenze, das Quoting der Gürtel dazu. Ein Wert, der das
    Muster nicht erfüllt, kommt aus einer manipulierten Registry — das ist ein
    Abbruch, keine Bereinigung.
    """
    if not IDENTIFIER_PATTERN.match(value):
        raise TenantScopeError(
            f"{field}={value!r} ist kein zulässiger Bezeichner und geht nicht in SQL."
        )
    return f'"{value}"'


async def apply_tenant_scope(
    session: AsyncSession,
    tenant: Tenant,
    *,
    extension_schema: str = "public",
) -> None:
    """Transaktion an den Mandanten binden und das Ergebnis nachprüfen.

    ``extension_schema`` hält die Erweiterungen (``pgcrypto``). Es steht auf dem
    ``search_path``, weil der Audit-Dienst ``pgp_sym_encrypt`` aufruft — aber als
    **zweiter** Eintrag und in einem Schema ohne Tabellen. Läge dort ein
    Magister-Tabellenrest, könnte eine im Mandantenschema fehlende Tabelle still
    auf ihn zurückfallen; genau deshalb prüft der Migrations-Runner, dass im
    Erweiterungsschema keine Anwendungstabellen liegen.
    """
    schema = quote_identifier(tenant.schema_name, field="schema_name")
    path = schema
    if extension_schema and extension_schema != tenant.schema_name:
        path = f"{schema}, {quote_identifier(extension_schema, field='extension_schema')}"

    # Reihenfolge: erst search_path, dann ROLE — die eingeschränkte Rolle soll
    # den Pfad hinterher nicht mehr setzen müssen.
    await session.execute(text(f"SET LOCAL search_path = {path}"))
    if tenant.db_role is not None and tenant.db_role != tenant.expected_session_user:
        # Nur nötig, wenn die Verbindung unter einem anderen Namen aufgebaut
        # wurde als der Mandantenrolle — der Einmandanten-Bestand. Bei mehreren
        # Mandanten erzwingt die Registry die eigene Anmelderolle; dann sitzt
        # die Verbindung von Anfang an richtig, und dieser Wechsel wäre für
        # sich genommen ohnehin keine Grenze.
        role = quote_identifier(tenant.db_role, field="db_role")
        await session.execute(text(f"SET LOCAL ROLE {role}"))

    await assert_tenant_scope(session, tenant)


async def assert_tenant_scope(session: AsyncSession, tenant: Tenant) -> None:
    """Die Zusicherung aus ADR-0013 D1: passt die Transaktion zum Mandanten?

    Gefragt wird die Datenbank, nicht die Anwendung — eine Anwendung, die ihren
    eigenen Zustand befragt, bestätigt sich nur selbst.
    """
    stmt = text("SELECT current_user, session_user, current_schemas(false)")
    row = (await session.execute(stmt)).one()
    current_user = str(row[0])
    session_user = str(row[1])
    schemas = [str(s) for s in (row[2] or [])]

    # session_user zuerst: er ist der härtere Beleg. current_user lässt sich in
    # der Transaktion per SET ROLE verschieben, session_user nicht — und weil
    # Postgres SET ROLE gegen den Sitzungsbenutzer prüft, entscheidet genau er,
    # in welche fremden Rollen überhaupt gewechselt werden könnte.
    expected_session_user = tenant.expected_session_user
    if expected_session_user is not None and session_user != expected_session_user:
        raise TenantScopeError(
            f"Mandant {tenant.slug!r} erwartet die Verbindung als "
            f"{expected_session_user!r}, sie läuft aber als {session_user!r}. "
            "Abbruch vor dem ersten Query."
        )
    if tenant.db_role is not None and current_user != tenant.db_role:
        raise TenantScopeError(
            f"Mandant {tenant.slug!r} erwartet die Rolle {tenant.db_role!r}, "
            f"die Transaktion läuft als {current_user!r}. Abbruch vor dem ersten Query."
        )
    if not schemas or schemas[0] != tenant.schema_name:
        raise TenantScopeError(
            f"Mandant {tenant.slug!r} erwartet {tenant.schema_name!r} an erster "
            f"Stelle des search_path, gefunden: {schemas or 'leer'}. "
            "Abbruch vor dem ersten Query."
        )
