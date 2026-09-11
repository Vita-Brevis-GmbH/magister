"""Nach einer Migration steht es im Protokoll des Kunden (ADR-0021 D2).

Die harte Regel verlangt ein kundensichtbares Audit-Ereignis bei jedem Rollout
in ein Kundenschema. Die Konsole kann es nicht schreiben — der Kundenschlüssel
liegt dort ausdrücklich nicht (ADR-0016 D8) —, also schreibt es die Stelle, die
migriert.

Zweiter Teil: der **gemeldete** Stand kommt aus `alembic_version` im Schema und
nicht aus einer Erwartung. Bis ADR-0021 trug `tenants.schema_version` in der
Konsole den Wert aus `COCKPIT_EXPECTED_SCHEMA_VERSION` — und genau diese Spalte
fährt die Versions-Schranke.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.audit.service import AuditFilter, AuditService
from magister_api.cli._migration_record import ROLLOUT_ACTOR, read_head, record_migration
from magister_api.config import Settings
from magister_api.tenancy.console_report import read_schema_head
from magister_api.tenancy.keys import attach_keys, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant, TenantStatus

pytestmark = pytest.mark.asyncio

HEAD = "0099_teststand"


@pytest_asyncio.fixture
async def with_alembic_version(engine: AsyncEngine) -> None:
    """`alembic_version` gibt es in jeder echten Installation.

    Die Integrationstests bauen ihr Schema mit `create_all`, und Alembic läuft
    dabei nicht — ohne diese Zeile prüfte der Test eine Umgebung, die es nicht
    gibt. Dieselbe Überlegung wie in `test_backup_verify_cli.py`.
    """
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num varchar(32) NOT NULL PRIMARY KEY)"
        )
        await conn.exec_driver_sql("DELETE FROM alembic_version")
        await conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": HEAD})


def _tenant(database_url: str) -> Tenant:
    return Tenant(
        slug="testkunde",
        name="Testkunde",
        dsn=database_url,
        schema_name="public",
        db_role=None,
        schema_version="",
        status=TenantStatus.ACTIVE,
        console_id=None,
    )


async def _events(engine: AsyncEngine, settings: Settings) -> list[dict[str, Any]]:
    """Ereignisse über den Dienst lesen — nie `SELECT payload` (CLAUDE.md)."""
    keys = resolve_tenant_keys(
        "testkunde",
        fallback_audit_key=settings.audit_key.get_secret_value(),
        fallback_audit_key_id=settings.audit_key_id,
        fallback_secrets_key=settings.app_secrets_key(),
        single_tenant=True,
    )
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        attach_keys(session, keys)
        listing = await AuditService(session, settings).list(
            filter=AuditFilter(action="schema_migrated"), limit=10
        )
    return [
        {"actor": r.actor_upn, "target": r.target_id, "payload": r.payload} for r in listing.items
    ]


@pytest.mark.usefixtures("with_alembic_version")
class TestTheCustomerSeesIt:
    async def test_the_migration_lands_in_the_customers_audit_trail(
        self, engine: AsyncEngine, database_url: str, app_settings: Settings
    ) -> None:
        outcome = await record_migration(
            _tenant(database_url),
            app_settings,
            before="0098_davor",
            dump="testkunde-20260911T090000Z-pre-migration.dump.age",
            single_tenant=True,
        )
        assert outcome.audited, outcome.notes
        assert outcome.head == HEAD

        events = await _events(engine, app_settings)
        assert len(events) == 1
        event = events[0]
        assert event["actor"] == ROLLOUT_ACTOR
        assert event["target"] == "public"
        assert event["payload"]["from_revision"] == "0098_davor"
        assert event["payload"]["to_revision"] == HEAD
        # Der Dateiname, nicht der Pfad: wohin der Betreiber seine Dumps legt,
        # ist keine Auskunft für den Kunden.
        assert event["payload"]["dump"].endswith(".dump.age")
        assert "/" not in event["payload"]["dump"]

    async def test_without_a_dump_the_event_says_so(
        self, engine: AsyncEngine, database_url: str, app_settings: Settings
    ) -> None:
        """`--no-dump` ist erlaubt, aber es bleibt im Protokoll stehen.

        Wer ohne Rückfahrkarte migriert, soll das nicht vor dem Kunden
        verbergen können.
        """
        await record_migration(
            _tenant(database_url), app_settings, before=None, dump=None, single_tenant=True
        )
        events = await _events(engine, app_settings)
        assert events[0]["payload"]["dump"].startswith("keiner")
        assert events[0]["payload"]["from_revision"] == "unbekannt"


@pytest.mark.usefixtures("with_alembic_version")
class TestTheReportedStandIsMeasured:
    async def test_the_head_comes_from_alembic_version(
        self, engine: AsyncEngine, database_url: str, app_settings: Settings
    ) -> None:
        assert await read_head(_tenant(database_url), app_settings) == HEAD

    async def test_a_changed_schema_changes_the_answer(
        self, engine: AsyncEngine, database_url: str, app_settings: Settings
    ) -> None:
        """Der Punkt der ganzen Übung: es ist eine Messung, keine Erwartung."""
        async with engine.begin() as conn:
            await conn.exec_driver_sql("UPDATE alembic_version SET version_num = '0100_danach'")
        assert await read_head(_tenant(database_url), app_settings) == "0100_danach"

    async def test_nothing_is_reported_without_a_console(
        self, database_url: str, app_settings: Settings
    ) -> None:
        """Einzelinstallation: der Stand steht im Schema, und das genügt."""
        assert not app_settings.console_registry_url
        outcome = await record_migration(
            _tenant(database_url), app_settings, before=None, dump=None, single_tenant=True
        )
        assert not outcome.reported
        # Und kein Hinweis, der nach einem Fehler klingt: es gibt nichts zu
        # melden, das ist kein Mangel.
        assert not [n for n in outcome.notes if "Konsole nicht benachrichtigt" in n]


class TestNoAlembicVersion:
    async def test_a_schema_without_the_table_reports_nothing(
        self, engine: AsyncEngine, database_url: str, app_settings: Settings
    ) -> None:
        """Kein Stand ist kein Fehler — aber auch keine Meldung.

        Eine Meldung „unbekannt“ würde in der Konsole als Messung erscheinen
        und wäre schlechter als gar keine.
        """
        async with engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            assert await read_schema_head(session, "public") is None
        outcome = await record_migration(
            _tenant(database_url), app_settings, before=None, dump=None, single_tenant=True
        )
        assert outcome.head is None
        assert not outcome.reported
        assert any("alembic_version" in n for n in outcome.notes)


class TestSqlInjectionInTheSchemaName:
    async def test_a_hostile_schema_name_finds_nothing(
        self, engine: AsyncEngine, app_settings: Settings
    ) -> None:
        """Der Schemaname kommt aus der Registry und geht in SQL.

        Er ist dort geprüft, und hier wird er über `to_regclass` als
        Bind-Parameter geprüft, bevor er in ein Statement kommt. Ein Name, den
        es nicht gibt, liefert `None` — kein Fehler, keine Ausführung.
        """
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            assert await read_schema_head(session, 'public"; DROP TABLE schools; --') is None
            # Und die Tabelle steht noch.
            assert (
                await session.execute(text("SELECT to_regclass('public.schools')"))
            ).scalar() is not None
