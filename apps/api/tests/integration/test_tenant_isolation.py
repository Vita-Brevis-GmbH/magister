"""Die Trennung wird von Postgres erzwungen, nicht von der Anwendung.

Der Abnahmetest aus Phase 1 (ADR-0013 D1): eine Mandantenrolle kommt an das
Schema eines anderen Mandanten **nicht** heran. Bewusst gegen eine echte
Datenbank mit echten Rollen — eine Zusicherung, die nur im Mock gilt, ist keine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from magister_api.tenancy.registry import Tenant, TenantStatus
from magister_api.tenancy.scope import TenantScopeError, apply_tenant_scope

pytestmark = pytest.mark.asyncio

ALPHA = "iso_alpha"
BETA = "iso_beta"


#: Passwort der Testrollen. Frei erfunden und nur in dieser Datei gültig.
#:
#: Warum überhaupt eines: ohne Passwort läuft dieser Test nur auf einem
#: Cluster mit ``trust``-Authentisierung. Das ist eine unsichtbare Annahme —
#: auf einem Cluster mit ``scram-sha-256`` scheitert er mit
#: ``InvalidPasswordError``, und das sieht aus wie ein kaputtes Testkonto und
#: nicht wie eine fehlende Zeile in der Vorbereitung.
ROLE_PASSWORD = "test-rollenpasswort"  # noqa: S105


def _dsn(base: str, user: str) -> str:
    """Denselben DSN mit anderer Anmelderolle.

    ``render_as_string(hide_password=False)`` und nicht ``str(url)``: letzteres
    ersetzt das Passwort durch ``***``.
    """
    from sqlalchemy.engine import make_url

    return (
        make_url(base)
        .set(username=user, password=ROLE_PASSWORD)
        .render_as_string(hide_password=False)
    )


def _tenant(slug: str, dsn: str) -> Tenant:
    return Tenant(
        slug=slug,
        name=slug,
        dsn=dsn,
        schema_name=f"t_{slug}",
        db_role=f"r_{slug}",
        schema_version="",
        status=TenantStatus.ACTIVE,
        hostname=f"{slug}.test",
    )


@pytest_asyncio.fixture
async def two_tenants(engine: AsyncEngine, database_url: str) -> AsyncIterator[dict[str, object]]:
    """Zwei Mandanten anlegen, wie das Onboarding-Runbook es tut.

    Der entscheidende Schritt ist das ``REVOKE`` — ohne es darf in Postgres
    jede Rolle über ``PUBLIC`` in jedes Schema hineinsehen.
    """
    async with engine.begin() as conn:
        for slug in (ALPHA, BETA):
            await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS t_{slug} CASCADE")
            await conn.exec_driver_sql(f"DROP ROLE IF EXISTS r_{slug}")
        for slug in (ALPHA, BETA):
            create = f"CREATE ROLE r_{slug} LOGIN PASSWORD '{ROLE_PASSWORD}'"
            await conn.exec_driver_sql(create)
            await conn.exec_driver_sql(f"CREATE SCHEMA t_{slug} AUTHORIZATION r_{slug}")
            await conn.exec_driver_sql(f"REVOKE ALL ON SCHEMA t_{slug} FROM PUBLIC")
            await conn.exec_driver_sql(f"GRANT USAGE, CREATE ON SCHEMA t_{slug} TO r_{slug}")
            await conn.exec_driver_sql(
                f"CREATE TABLE t_{slug}.schueler (id int primary key, name text)"
            )
            # slug ist eine Konstante dieses Moduls, kein Eingabewert.
            insert = f"INSERT INTO t_{slug}.schueler VALUES (1, '{slug}-kind')"  # noqa: S608
            await conn.exec_driver_sql(insert)
            await conn.exec_driver_sql(f"ALTER TABLE t_{slug}.schueler OWNER TO r_{slug}")

    engines: dict[str, AsyncEngine] = {}
    tenants: dict[str, Tenant] = {}
    for slug in (ALPHA, BETA):
        tenant = _tenant(slug, _dsn(database_url, f"r_{slug}"))
        tenants[slug] = tenant
        engines[slug] = create_async_engine(tenant.dsn, pool_size=1, max_overflow=0)

    yield {"tenants": tenants, "engines": engines}

    for eng in engines.values():
        await eng.dispose()
    async with engine.begin() as conn:
        for slug in (ALPHA, BETA):
            await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS t_{slug} CASCADE")
            await conn.exec_driver_sql(f"DROP ROLE IF EXISTS r_{slug}")


def _sm(bundle: dict[str, object], slug: str) -> async_sessionmaker:  # type: ignore[type-arg]
    engines: dict[str, AsyncEngine] = bundle["engines"]  # type: ignore[assignment]
    return async_sessionmaker(engines[slug], expire_on_commit=False, autoflush=False)


def _tenant_of(bundle: dict[str, object], slug: str) -> Tenant:
    tenants: dict[str, Tenant] = bundle["tenants"]  # type: ignore[assignment]
    return tenants[slug]


class TestTheContract:
    async def test_a_tenant_reads_its_own_schema(self, two_tenants: dict[str, object]) -> None:
        tenant = _tenant_of(two_tenants, ALPHA)
        async with _sm(two_tenants, ALPHA)() as session:
            await apply_tenant_scope(session, tenant)
            rows = (await session.execute(text("SELECT name FROM schueler"))).scalars().all()
        assert rows == [f"{ALPHA}-kind"]

    async def test_a_tenant_cannot_read_the_other_schema(
        self, two_tenants: dict[str, object]
    ) -> None:
        """Der Abnahmetest: qualifizierter Zugriff auf das Nachbarschema."""
        tenant = _tenant_of(two_tenants, ALPHA)
        async with _sm(two_tenants, ALPHA)() as session:
            await apply_tenant_scope(session, tenant)
            with pytest.raises(ProgrammingError) as exc:
                # Der Angriff selbst — deshalb steht der Schemaname hier im
                # Klartext im SQL. noqa S608: genau das ist der Prüfgegenstand.
                await session.execute(text(f"SELECT name FROM t_{BETA}.schueler"))  # noqa: S608
        assert "permission denied" in str(exc.value).lower()

    async def test_a_tenant_cannot_switch_to_the_other_role(
        self, two_tenants: dict[str, object]
    ) -> None:
        """Der Befund, der die Bauart bestimmt hat.

        Mit einer *gemeinsamen* Anmelderolle gelingt ``SET ROLE`` in den
        Nachbarmandanten, weil Postgres gegen den Sitzungsbenutzer prüft. Mit
        eigener Anmelderolle je Mandant gibt es diese Rolle hier nicht.
        """
        tenant = _tenant_of(two_tenants, ALPHA)
        async with _sm(two_tenants, ALPHA)() as session:
            await apply_tenant_scope(session, tenant)
            with pytest.raises(ProgrammingError) as exc:
                await session.execute(text(f'SET ROLE "r_{BETA}"'))
        assert "permission denied" in str(exc.value).lower()

    async def test_the_other_schema_is_invisible_in_the_catalog(
        self, two_tenants: dict[str, object]
    ) -> None:
        # Nicht nur die Daten sind weg, auch die Namen: information_schema
        # filtert nach Rechten. Ein Angreifer erfährt nicht einmal, was es gibt.
        tenant = _tenant_of(two_tenants, ALPHA)
        async with _sm(two_tenants, ALPHA)() as session:
            await apply_tenant_scope(session, tenant)
            count = (
                await session.execute(
                    text("SELECT count(*) FROM information_schema.tables WHERE table_schema = :s"),
                    {"s": f"t_{BETA}"},
                )
            ).scalar()
        assert count == 0

    async def test_a_forgotten_filter_is_an_error_not_foreign_rows(
        self, two_tenants: dict[str, object]
    ) -> None:
        """Die eigentliche Zusage von D1, an einem unqualifizierten Query.

        ``schueler`` gibt es in beiden Schemas. Beim falschen Mandanten steht es
        nicht auf dem search_path — das Ergebnis ist ein Fehler, nicht die
        Tabelle des Nachbarn.
        """
        beta = _tenant_of(two_tenants, BETA)
        async with _sm(two_tenants, ALPHA)() as session:
            # Absichtlich falsch verdrahtet: Beta-Mandant auf Alphas Verbindung.
            with pytest.raises(TenantScopeError, match="erwartet die Verbindung als"):
                await apply_tenant_scope(session, beta)


class TestTheAssertion:
    async def test_it_rejects_a_mismatched_connection(self, two_tenants: dict[str, object]) -> None:
        # Genau der Fall, den die Zusicherung abfangen soll: die Sitzung kommt
        # aus dem falschen Pool. Ohne die Prüfung liefe die Anfrage einfach
        # gegen die Daten des Nachbarn.
        alpha = _tenant_of(two_tenants, ALPHA)
        beta = _tenant_of(two_tenants, BETA)
        async with _sm(two_tenants, BETA)() as session:
            with pytest.raises(TenantScopeError) as exc:
                await apply_tenant_scope(session, alpha)
        assert beta.db_role is not None and beta.db_role in str(exc.value)

    async def test_the_scope_ends_with_the_transaction(
        self, two_tenants: dict[str, object]
    ) -> None:
        """``SET LOCAL`` heisst: der Pool trägt nichts weiter."""
        tenant = _tenant_of(two_tenants, ALPHA)
        sm = _sm(two_tenants, ALPHA)
        async with sm() as session:
            await apply_tenant_scope(session, tenant)
            await session.commit()
            # Nach dem Commit ist der search_path zurück auf der Vorgabe.
            schemas = (await session.execute(text("SELECT current_schemas(false)"))).scalar()
        assert f"t_{ALPHA}" not in (schemas or [])

    async def test_pgcrypto_stays_reachable_through_the_extension_schema(
        self, two_tenants: dict[str, object]
    ) -> None:
        """Sonst bricht der Audit-Dienst, sobald das Schema nicht 'public' ist.

        Deshalb steht das Erweiterungsschema als zweiter Eintrag auf dem
        search_path — und deshalb darf dort keine Anwendungstabelle liegen.
        """
        tenant = _tenant_of(two_tenants, ALPHA)
        async with _sm(two_tenants, ALPHA)() as session:
            await apply_tenant_scope(session, tenant, extension_schema="public")
            ok = (
                await session.execute(
                    text("SELECT length(pgp_sym_encrypt('geheim', 'k')::text) > 0")
                )
            ).scalar()
        assert ok is True
