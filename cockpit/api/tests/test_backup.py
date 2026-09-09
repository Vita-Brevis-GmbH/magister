"""Sicherung, Prüf-Wiederherstellung, Wiederherstellung (ADR-0016).

Die Abnahmekriterien, soweit hier prüfbar:

* Ein Kunde wird aus einem Dump wiederhergestellt, **ohne** dass ein anderer
  Kunde etwas merkt — hier sogar ohne dass das Produktivschema geöffnet wird.
* Ein absichtlich beschädigter Dump fällt in der Prüfung auf.
* Ohne öffentlichen Schlüssel wird **nicht** geschrieben statt unverschlüsselt.

Gegen echtes Postgres, echtes ``pg_dump``, echtes ``age``. Eine Sicherung, die
nur im Mock funktioniert, ist keine.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.services.backup import (
    BackupError,
    backup_path,
    check_recipient,
    create_backup,
    verify_checksum,
)
from cockpit_api.services.restore import (
    RestoreError,
    restore_dump,
    scratch_database_name,
    verify_backup,
)

pytestmark = pytest.mark.asyncio

SLUG = "bkp"
SCHEMA = f"t_{SLUG}"
NACHBAR = "t_nachbar"


def _tools_present() -> bool:
    return all(shutil.which(t) for t in ("pg_dump", "pg_restore", "age", "age-keygen"))


@pytest.fixture(scope="module")
def age_keys(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
    """Ein age-Schlüsselpaar. Öffentlich zum Schreiben, privat zum Prüfen.

    Getrennt gehalten wie in Produktion: der Sicherungsteil bekommt nur den
    öffentlichen Teil, und nur die Prüfung bekommt die Identitätsdatei.
    """
    if not _tools_present():
        pytest.skip("pg_dump/pg_restore/age/age-keygen nicht installiert")
    directory = tmp_path_factory.mktemp("age")
    identity = directory / "backup-identity.txt"
    # Feste Argumentliste, keine Shell.
    proc = subprocess.run(
        ["age-keygen", "-o", str(identity)], capture_output=True, text=True, check=True
    )
    recipient = ""
    for line in (proc.stderr or "").splitlines():
        if "public key:" in line.lower():
            recipient = line.split(":", 1)[1].strip()
    assert recipient, "age-keygen hat keinen öffentlichen Schlüssel gemeldet"
    return recipient, identity


@pytest.fixture
def admin_dsn(magister_admin_dsn: str) -> str:
    return magister_admin_dsn


@pytest.fixture
def tenant_data(magister_admin_dsn: str) -> Iterator[dict[str, int]]:
    """Zwei Kundenschemas mit Inhalt: der gesicherte und ein Nachbar.

    Der Nachbar ist der Prüfstein für „ohne dass ein anderer Kunde etwas
    merkt": er wird vorher und nachher gezählt.
    """
    import asyncio

    ddl = [
        f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE",
        f"DROP SCHEMA IF EXISTS {NACHBAR} CASCADE",
        f"CREATE SCHEMA {SCHEMA}",
        f"CREATE SCHEMA {NACHBAR}",
    ]
    for schema, rows in ((SCHEMA, 12), (NACHBAR, 3)):
        ddl += [
            f"CREATE TABLE {schema}.alembic_version (version_num varchar(32) primary key)",
            f"INSERT INTO {schema}.alembic_version VALUES ('0044_local_admin_totp')",
            f"CREATE TABLE {schema}.schools (id serial primary key, name text)",
            f"CREATE TABLE {schema}.classes (id serial primary key, name text)",
            f"CREATE TABLE {schema}.sessions (id text primary key)",
            f"CREATE TABLE {schema}.app_settings (id int primary key)",
            f"CREATE TABLE {schema}.role_assignments (id serial primary key)",
            # payload als bytea, wie pgcrypto es liefert.
            f"CREATE TABLE {schema}.audit_events (id serial primary key, payload bytea)",
            f"INSERT INTO {schema}.schools (name) "
            f"SELECT 'Schule ' || g FROM generate_series(1, {rows}) g",
            f"INSERT INTO {schema}.audit_events (payload) "
            f"SELECT pgp_sym_encrypt('{{\"a\": 1}}', 'k') FROM generate_series(1, 4)",
        ]

    async def build() -> None:
        engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
                for statement in ddl:
                    await conn.exec_driver_sql(statement)
        finally:
            await engine.dispose()

    asyncio.run(build())
    yield {"schools": 12, "nachbar_schools": 3}

    async def teardown() -> None:
        engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
                await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {NACHBAR} CASCADE")
        finally:
            await engine.dispose()

    asyncio.run(teardown())


async def _count(dsn: str, schema: str, table: str) -> int:
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return int(
                (
                    await conn.execute(text(f'SELECT count(*) FROM "{schema}"."{table}"'))
                ).scalar_one()
            )
    finally:
        await engine.dispose()


class TestEncryptionIsNotOptional:
    """Läuft ohne Postgres."""

    @pytest.mark.parametrize("bad", ["", "   ", "nicht-age", "age1zzz", "AGE1" + "a" * 58])
    async def test_a_bad_recipient_refuses_to_write(self, bad: str) -> None:
        """Ein falscher Empfänger darf nicht in eine unverschlüsselte Datei führen.

        Auf einem Share sind die Dumps für mehr Personen und Systeme
        erreichbar als in der Datenbank — deshalb Abbruch, nicht Warnung.
        """
        with pytest.raises(BackupError, match="age-Schlüssel"):
            check_recipient(bad)

    async def test_the_path_carries_slug_kind_and_time(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        when = datetime(2026, 9, 9, 3, 15, tzinfo=UTC)
        path = backup_path(tmp_path, "musterstadt", "daily", when)
        assert path.parent.name == "musterstadt"
        assert path.name == "musterstadt-20260909T031500Z-daily.dump.age"

    async def test_a_bad_slug_never_reaches_a_path(self, tmp_path: Path) -> None:
        with pytest.raises(BackupError, match="Bezeichner"):
            backup_path(tmp_path, "../../etc", "daily", None)  # type: ignore[arg-type]


@pytest.mark.usefixtures("tenant_data")
class TestBackupAndVerify:
    async def test_a_backup_is_written_encrypted_and_verifies(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        assert artifact.size_bytes > 0
        # Verschlüsselt: die age-Kopfzeile steht drin, der Klartext nicht.
        head = artifact.path.read_bytes()[:200]
        assert b"age-encryption.org" in head
        assert b"PGDMP" not in artifact.path.read_bytes(), "der Dump liegt im Klartext"
        assert verify_checksum(artifact.path, artifact.checksum_sha256)

        result = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
            expected_schema_version="0044_local_admin_totp",
            expected_checksum=artifact.checksum_sha256,
            reference_row_counts={"schools": 12},
        )
        assert result.ok, result.detail
        assert "Alembic-Version 0044_local_admin_totp" in result.detail
        assert "Audit-Payloads verschlüsselt" in result.detail

    async def test_the_neighbour_tenant_never_notices(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Das Abnahmekriterium.

        Die Prüf-Wiederherstellung läuft in einer eigenen Datenbank. Das
        Produktivschema des gesicherten Kunden wird nur gelesen, das des
        Nachbarn nicht einmal geöffnet.
        """
        recipient, identity = age_keys
        before = await _count(admin_dsn, NACHBAR, "schools")
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        result = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
        )
        assert result.ok, result.detail
        assert await _count(admin_dsn, NACHBAR, "schools") == before == 3
        # Und der gesicherte Kunde selbst steht auch noch da.
        assert await _count(admin_dsn, SCHEMA, "schools") == 12

    async def test_a_corrupted_dump_is_caught(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Das zweite Abnahmekriterium: absichtlich beschädigt.

        Erst über die Prüfsumme — ein veränderter Dump ist ein **Vorfall** und
        kein Wiederherstellungsproblem, und das soll man unterscheiden können,
        bevor man entschlüsselt.
        """
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        raw = bytearray(artifact.path.read_bytes())
        raw[len(raw) // 2] ^= 0xFF  # ein Bit in der Mitte kippen
        artifact.path.write_bytes(bytes(raw))

        assert not verify_checksum(artifact.path, artifact.checksum_sha256)
        result = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
            expected_checksum=artifact.checksum_sha256,
        )
        assert not result.ok
        assert "Prüfsumme" in result.detail and "Vorfall" in result.detail

    async def test_a_corrupted_dump_without_a_known_checksum_still_fails(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Auch ohne Prüfsumme darf ein kaputter Dump nicht als geprüft gelten.

        Die Prüfsumme ist die schnelle Erkennung; das Einspielen ist die
        eigentliche. Wer nur der Prüfsumme traut, hat ein Backup, das
        bitgenau stimmt und trotzdem nicht einspielt.
        """
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        raw = bytearray(artifact.path.read_bytes())
        raw[len(raw) // 2] ^= 0xFF
        artifact.path.write_bytes(bytes(raw))

        result = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
        )
        assert not result.ok, result.detail

    async def test_a_wrong_schema_version_is_a_problem(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        # Ohne diese Prüfung spielt man einen Dump ein, zu dem der Codestand
        # nicht passt — und merkt es an falschen Abfragen, nicht am Restore.
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        result = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
            expected_schema_version="0099_gibtsnicht",
        )
        assert not result.ok
        assert "0099_gibtsnicht" in result.detail

    async def test_a_shrunken_dump_is_a_problem(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Zeilenzahlen in plausibler Grössenordnung, nicht auf Gleichheit.

        Ein Dump mit 12 statt 300 Zeilen ist kaputt; einer mit 298 ist normal,
        weil zwischen Sicherung und Prüfung weitergearbeitet wurde.
        """
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        knapp = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
            reference_row_counts={"schools": 14},  # 12 von 14 ist plausibel
        )
        assert knapp.ok, knapp.detail
        weg = await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
            reference_row_counts={"schools": 300},  # 12 von 300 ist kaputt
        )
        assert not weg.ok
        assert "12 Zeilen im Dump gegen 300" in weg.detail

    async def test_the_scratch_database_is_gone_afterwards(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="daily",
            share_root=tmp_path,
            recipient=recipient,
        )
        await verify_backup(
            admin_dsn=admin_dsn,
            dump_path=artifact.path,
            identity_file=identity,
            slug=SLUG,
            schema_name=SCHEMA,
        )
        engine = create_async_engine(admin_dsn, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                left = (
                    await conn.execute(
                        text("SELECT count(*) FROM pg_database WHERE datname LIKE :p"),
                        {"p": f"v_{SLUG}_%"},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
        assert left == 0, "eine Wegwerf-Datenbank ist liegengeblieben"


@pytest.mark.usefixtures("tenant_data")
class TestRestoreBesideProduction:
    async def test_a_restore_lands_in_its_own_database(
        self, admin_dsn: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Daneben, nie darüber (ADR-0016 D5).

        Die Wiederherstellung geht in eine eigene Datenbank; das
        Produktivschema wird nicht einmal geöffnet. Umschalten ist danach ein
        Registry-Eintrag — die Registry trägt DSN *und* Schema.
        """
        recipient, identity = age_keys
        artifact = await create_backup(
            dsn=admin_dsn,
            schema_name=SCHEMA,
            slug=SLUG,
            kind="manual",
            share_root=tmp_path,
            recipient=recipient,
        )
        target = scratch_database_name("r_{slug}_{stamp}", SLUG)
        try:
            await restore_dump(
                admin_dsn=admin_dsn,
                dump_path=artifact.path,
                identity_file=identity,
                target_database=target,
                expected_checksum=artifact.checksum_sha256,
            )
            # hide_password=False, sonst steht im DSN ``***`` statt des
            # Passworts — genau der Fehler, den _admin_dsn_for hatte.
            side = make_url(admin_dsn).set(database=target).render_as_string(hide_password=False)
            assert await _count(side, SCHEMA, "schools") == 12
            # Produktion unangetastet.
            assert await _count(admin_dsn, SCHEMA, "schools") == 12
            assert await _count(admin_dsn, NACHBAR, "schools") == 3
        finally:
            from cockpit_api.services.restore import _drop_database

            await _drop_database(admin_dsn, target)

    async def test_a_missing_identity_file_says_where_it_belongs(
        self, admin_dsn: str, tmp_path: Path
    ) -> None:
        """Der Widerspruch zwischen D2 und D4, ausgesprochen.

        D2 sagt, der private Schlüssel liege nie auf dem Anwendungsserver;
        D4 verlangt eine Prüf-Wiederherstellung, die entschlüsseln muss.
        Auflösung: dieses Werkzeug läuft dort, wo der Schlüssel liegt. Die
        Fehlermeldung muss das sagen, sonst konfiguriert es jemand doch auf
        dem Anwendungsserver.
        """
        dump = tmp_path / "irgendwas.dump.age"
        dump.write_bytes(b"x")
        with pytest.raises(RestoreError, match="nicht auf dem Anwendungsserver"):
            await restore_dump(
                admin_dsn=admin_dsn,
                dump_path=dump,
                identity_file=tmp_path / "fehlt.txt",
                target_database="r_egal_1",
            )
