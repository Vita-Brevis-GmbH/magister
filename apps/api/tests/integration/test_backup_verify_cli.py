"""``magister-cli backup verify`` auf einer Einzelinstallation (ADR-0016 D9).

Eine Gemeinde mit einem Server bekommt keinen Plattform-Betrieb — aber sie
bekommt die Zusage aus D4: ein Backup gilt erst als Backup, wenn es eingespielt
wurde. Geprüft wird gegen echtes ``pg_dump``/``pg_restore`` und echtes ``age``.
Eine Prüf-Wiederherstellung, die nur im Mock läuft, prüft nichts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from magister_api.cli.backup import (
    EXPECTED_TABLES,
    BackupVerifyError,
    libpq_env,
    sha256_file,
    verify,
)

pytestmark = pytest.mark.asyncio


def _tools_present() -> bool:
    return all(shutil.which(t) for t in ("pg_dump", "pg_restore", "age", "age-keygen"))


@pytest.fixture(scope="module")
def age_keys(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
    """Ein Schlüsselpaar. Öffentlich zum Schreiben, privat zum Prüfen.

    Getrennt wie in Produktion: die Sidecar bekommt nur den öffentlichen Teil.
    """
    if not _tools_present():
        pytest.skip("pg_dump/pg_restore/age/age-keygen nicht installiert")
    directory = tmp_path_factory.mktemp("age")
    identity = directory / "backup-identity.txt"
    keygen = shutil.which("age-keygen") or "age-keygen"
    proc = subprocess.run(  # noqa: S603 — feste Argumente dieses Tests
        [keygen, "-o", str(identity)], capture_output=True, text=True, check=True
    )
    recipient = ""
    for line in (proc.stderr or "").splitlines():
        if "public key:" in line.lower():
            recipient = line.split(":", 1)[1].strip()
    assert recipient
    return recipient, identity


@pytest_asyncio.fixture
async def seeded(engine: AsyncEngine) -> AsyncIterator[None]:
    """Eine Schule, ein verschlüsselter Audit-Payload — und ``alembic_version``.

    Letzteres, weil die Integrationstests ihr Schema mit
    ``Base.metadata.create_all`` bauen und Alembic dabei nicht läuft. In einer
    echten Installation gibt es die Tabelle immer; ohne sie prüfte dieser Test
    eine Umgebung, die es nicht gibt, und die Prüfung würde zu Recht
    „Tabellen fehlen" melden. Dieselbe Überlegung wie bei den partiellen
    Indizes in ``conftest.py``.
    """
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num varchar(32) NOT NULL PRIMARY KEY)"
        )
        await conn.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('0044_local_admin_totp') "
            "ON CONFLICT DO NOTHING"
        )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO schools (name, kuerzel, scope_short, created_at, "
                "updated_at) VALUES ('Probeschule', 'prb', 'mud', now(), now())"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO audit_events (ts, action, target_kind, target_id, "
                "request_id, payload, key_id) VALUES (now(), 'test', 'school', '1', "
                "'r1', pgp_sym_encrypt('{\"a\": 1}', 'kundenschluessel'), 'v1')"
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")


def _dump(database_url: str, recipient: str, target: Path) -> Path:
    """Wie ``deploy/compose/pg-backup/backup.sh`` es tut: custom + age."""
    url = make_url(database_url)
    env = libpq_env(database_url)
    read_fd, write_fd = os.pipe()
    try:
        first = subprocess.Popen(  # noqa: S603
            [
                shutil.which("pg_dump") or "pg_dump",
                f"--dbname={url.database}",
                "--no-owner",
                "--no-privileges",
                "--format=custom",
            ],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=write_fd,
            stderr=subprocess.DEVNULL,
        )
        second = subprocess.Popen(  # noqa: S603
            [shutil.which("age") or "age", "-r", recipient, "-o", str(target)],
            stdin=read_fd,
            stderr=subprocess.DEVNULL,
        )
    finally:
        os.close(write_fd)
        os.close(read_fd)
    assert second.wait() == 0
    assert first.wait() == 0
    return target


@pytest.mark.usefixtures("seeded")
class TestVerify:
    async def test_a_good_dump_verifies(
        self, database_url: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        recipient, identity = age_keys
        dump = _dump(database_url, recipient, tmp_path / "magister.dump.age")
        # Verschlüsselt: die age-Kopfzeile steht drin, der Klartext nicht.
        assert b"age-encryption.org" in dump.read_bytes()[:200]
        assert b"PGDMP" not in dump.read_bytes(), "der Dump liegt im Klartext"

        result = await verify(
            admin_dsn=database_url,
            dump=dump,
            identity=identity,
            expected_checksum=sha256_file(dump),
            expected_version="0044_local_admin_totp",
            keep=False,
        )
        assert result.ok, result.detail
        assert "Audit-Payloads verschlüsselt" in result.detail

    async def test_a_tampered_dump_is_refused_before_decrypting(
        self, database_url: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Eine veränderte Datei ist ein Vorfall, kein Wiederherstellungsproblem."""
        recipient, identity = age_keys
        dump = _dump(database_url, recipient, tmp_path / "magister.dump.age")
        good = sha256_file(dump)
        result = await verify(
            admin_dsn=database_url,
            dump=dump,
            identity=identity,
            expected_checksum=good[:-1] + ("0" if good[-1] != "0" else "1"),
            expected_version=None,
            keep=False,
        )
        assert not result.ok
        assert "Vorfall" in result.detail

    async def test_a_corrupted_dump_fails_on_restore(
        self, database_url: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        """Ohne bekannte Prüfsumme fällt es erst beim Einspielen auf — aber es fällt auf."""
        recipient, identity = age_keys
        dump = _dump(database_url, recipient, tmp_path / "magister.dump.age")
        raw = bytearray(dump.read_bytes())
        # Mitten in den Chiffretext, nicht in die Kopfzeile.
        middle = len(raw) // 2
        raw[middle] ^= 0xFF
        dump.write_bytes(bytes(raw))

        result = await verify(
            admin_dsn=database_url,
            dump=dump,
            identity=identity,
            expected_checksum=None,
            expected_version=None,
            keep=False,
        )
        assert not result.ok
        assert "Einspielen gescheitert" in result.detail

    async def test_a_wrong_schema_version_is_reported(
        self, database_url: str, age_keys: tuple[str, Path], tmp_path: Path
    ) -> None:
        recipient, identity = age_keys
        dump = _dump(database_url, recipient, tmp_path / "magister.dump.age")
        result = await verify(
            admin_dsn=database_url,
            dump=dump,
            identity=identity,
            expected_checksum=None,
            expected_version="0099_gibts_nicht",
            keep=False,
        )
        assert not result.ok
        assert "0099_gibts_nicht" in result.detail

    async def test_the_scratch_database_is_gone_afterwards(
        self, database_url: str, age_keys: tuple[str, Path], tmp_path: Path, engine: AsyncEngine
    ) -> None:
        """Sonst füllt die wöchentliche Prüfung den Cluster mit Wegwerf-Datenbanken."""
        recipient, identity = age_keys
        dump = _dump(database_url, recipient, tmp_path / "magister.dump.age")
        await verify(
            admin_dsn=database_url,
            dump=dump,
            identity=identity,
            expected_checksum=None,
            expected_version=None,
            keep=False,
        )
        async with engine.connect() as conn:
            left = (
                await conn.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname LIKE 'v_magister_%'")
                )
            ).scalar_one()
        assert int(left) == 0

    async def test_the_production_database_is_untouched(
        self, database_url: str, age_keys: tuple[str, Path], tmp_path: Path, engine: AsyncEngine
    ) -> None:
        """Geprüft wird in einer Wegwerf-Datenbank, nicht in der Produktion."""
        recipient, identity = age_keys

        async def schools() -> int:
            async with engine.connect() as conn:
                return int((await conn.execute(text("SELECT count(*) FROM schools"))).scalar_one())

        before = await schools()
        dump = _dump(database_url, recipient, tmp_path / "magister.dump.age")
        await verify(
            admin_dsn=database_url,
            dump=dump,
            identity=identity,
            expected_checksum=None,
            expected_version=None,
            keep=False,
        )
        assert await schools() == before


class TestGuards:
    async def test_a_missing_dump_is_named(self, tmp_path: Path) -> None:
        with pytest.raises(BackupVerifyError, match="fehlt"):
            await verify(
                admin_dsn="postgresql+asyncpg://x@localhost/x",
                dump=tmp_path / "gibts-nicht.dump.age",
                identity=tmp_path / "auch-nicht.txt",
                expected_checksum=None,
                expected_version=None,
                keep=False,
            )

    async def test_a_missing_identity_says_where_it_belongs(self, tmp_path: Path) -> None:
        """Der Text nennt die Grenze: dieses Werkzeug läuft, wo der Schlüssel liegt."""
        dump = tmp_path / "irgendwas.dump.age"
        dump.write_bytes(b"x")
        with pytest.raises(BackupVerifyError, match="private Backup-Schlüssel"):
            await verify(
                admin_dsn="postgresql+asyncpg://x@localhost/x",
                dump=dump,
                identity=tmp_path / "gibts-nicht.txt",
                expected_checksum=None,
                expected_version=None,
                keep=False,
            )

    async def test_the_expected_tables_are_a_small_stable_set(self) -> None:
        """Die Liste soll nicht mit jeder Migration mitwachsen.

        Sie soll merken, wenn ein Dump nur den halben Bestand enthält — dafür
        genügen die Tabellen, die es in jeder Installation gibt.
        """
        assert "alembic_version" in EXPECTED_TABLES
        assert "audit_events" in EXPECTED_TABLES
        assert len(EXPECTED_TABLES) < 10
