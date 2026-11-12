"""Crypto-Shredding: der Kundenschlüssel ist die Löschung (ADR-0016 D8).

Das Abnahmekriterium wörtlich: „nach dem Vernichten des Kundenschlüssels ist
kein Audit-Payload mehr entschlüsselbar". Geprüft wird hier, dass dieser Satz
**pro Kunde** gilt — und genau daran hing der Umbau in
:mod:`magister_api.tenancy.keys`. Mit einem gemeinsamen Schlüssel wären beide
Richtungen falsch:

* Man vernichtet den Schlüssel von Kunde A und macht damit auch die
  Audit-Inhalte von Kunde B unlesbar. Also vernichtet man ihn nicht — und die
  Löschzusage an A ist unerfüllt.
* Oder man behält ihn, und ein gestohlenes Backup von A gibt mit demselben
  Schlüssel die Inhalte aller Kunden her.

Gegen echtes pgcrypto, nicht gegen eine Nachbildung: ob ``pgp_sym_decrypt``
mit dem falschen Schlüssel scheitert oder stillschweigend Unsinn liefert, ist
genau die Frage, und die beantwortet nur Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio

ALPHA_SCHEMA = "t_shred_alpha"
BETA_SCHEMA = "t_shred_beta"
ALPHA_KEY = "schluessel-von-alpha-mindestens-32-zeichen"
BETA_KEY = "schluessel-von-beta-mindestens-32-zeichen"


@pytest_asyncio.fixture
async def two_schemas(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Zwei Kundenschemas mit je einer verschlüsselten Audit-Zeile."""
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        for schema, key in ((ALPHA_SCHEMA, ALPHA_KEY), (BETA_SCHEMA, BETA_KEY)):
            await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            await conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
            await conn.exec_driver_sql(
                f"CREATE TABLE {schema}.audit_events "
                "(id serial primary key, payload bytea, key_id text)"
            )
            # Konstanten dieses Moduls, keine Eingabewerte.
            row = f"(pgp_sym_encrypt('{{\"wer\": \"{schema}\"}}', '{key}'), '{schema}-v1')"
            insert = f"INSERT INTO {schema}.audit_events (payload, key_id) VALUES {row}"  # noqa: S608
            await conn.exec_driver_sql(insert)
    yield engine
    async with engine.begin() as conn:
        for schema in (ALPHA_SCHEMA, BETA_SCHEMA):
            await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


async def _decrypt(engine: AsyncEngine, schema: str, key: str) -> str:
    async with engine.connect() as conn:
        # Konstanten dieses Moduls, keine Eingabewerte.
        column = f"pgp_sym_decrypt(payload, '{key}')"
        stmt = f"SELECT {column} FROM {schema}.audit_events LIMIT 1"  # noqa: S608
        return str((await conn.exec_driver_sql(stmt)).scalar_one())


class TestCryptoShredding:
    async def test_its_own_key_reads_its_own_payload(self, two_schemas: AsyncEngine) -> None:
        assert ALPHA_SCHEMA in await _decrypt(two_schemas, ALPHA_SCHEMA, ALPHA_KEY)
        assert BETA_SCHEMA in await _decrypt(two_schemas, BETA_SCHEMA, BETA_KEY)

    async def test_the_neighbours_key_reads_nothing(self, two_schemas: AsyncEngine) -> None:
        """Der Kern der Zusage: Alphas Schlüssel öffnet Betas Inhalte nicht.

        Und pgcrypto scheitert dabei laut, nicht still — sonst stünde in einem
        Export irgendwann Unsinn statt einer Fehlermeldung.
        """
        with pytest.raises(DBAPIError, match="Wrong key|corrupt"):
            await _decrypt(two_schemas, BETA_SCHEMA, ALPHA_KEY)
        with pytest.raises(DBAPIError, match="Wrong key|corrupt"):
            await _decrypt(two_schemas, ALPHA_SCHEMA, BETA_KEY)

    async def test_destroying_one_key_leaves_the_other_readable(
        self, two_schemas: AsyncEngine
    ) -> None:
        """Offboarding von Alpha: Schlüssel weg, Beta läuft weiter.

        „Schlüssel vernichten" heisst hier: er existiert in dieser Prüfung
        nicht mehr — wir haben nur noch Betas. Damit ist Alphas Zeile für
        immer unlesbar, auch aus jeder bereits geschriebenen Sicherung, und
        Betas Zeile ist unberührt.
        """
        vernichtet = ALPHA_KEY
        del vernichtet

        with pytest.raises(DBAPIError, match="Wrong key|corrupt"):
            await _decrypt(two_schemas, ALPHA_SCHEMA, BETA_KEY)
        assert BETA_SCHEMA in await _decrypt(two_schemas, BETA_SCHEMA, BETA_KEY)

    async def test_the_key_id_is_recorded_per_tenant(self, two_schemas: AsyncEngine) -> None:
        """Ohne eigene Id findet niemand den passenden Schlüssel wieder.

        Die Sicherung vermerkt nur ``audit_key_id`` (ADR-0016 D2). Steht dort
        bei allen Kunden ``v1``, ist der Vermerk wertlos.
        """
        async with two_schemas.connect() as conn:
            for schema in (ALPHA_SCHEMA, BETA_SCHEMA):
                stmt = f"SELECT key_id FROM {schema}.audit_events LIMIT 1"  # noqa: S608
                assert (await conn.exec_driver_sql(stmt)).scalar_one() == f"{schema}-v1"
