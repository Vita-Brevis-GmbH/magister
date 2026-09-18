"""Der Vor-Migrations-Dump ist verschlüsselt (ADR-0021 D1, ADR-0016 D2).

Bis ADR-0021 schrieb ``dump_tenant()`` ein nacktes ``pg_dump --file=…``. Das
verstösst gegen eine harte Regel — und die Regel ist keine Formalie: ein
Schulschema enthält Namen, Klassen und Geburtsdaten von Minderjährigen, und
ein Dump liegt auf einem Share, der für mehr Personen und Systeme erreichbar
ist als die Datenbank.

Geprüft wird gegen echtes ``pg_dump`` und echtes ``age``, nicht gegen einen
Mock: der Punkt dieses Tests ist, dass auf der Platte **kein Klartext** landet,
und das kann nur ein echter Lauf zeigen.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from magister_api.cli._pipe import PipeError
from magister_api.cli.tenants import RECIPIENT_ENV, check_recipient, dump_tenant
from magister_api.tenancy.registry import Tenant, TenantStatus

# Kein modulweites `asyncio`-Mark: die Hälfte dieser Tests ist synchron, und
# ein Mark auf einer synchronen Funktion ist eine Warnung bei jedem Lauf.
#
# Die async-Tests hängen an der `engine`-Fixture — nicht, weil sie die
# Datenbank brauchen, sondern weil sie ein Schema MIT Tabellen brauchen. Ein
# Dump eines leeren Schemas wäre gültig und würde nichts beweisen.
#
# Alles Blockierende läuft über `asyncio.to_thread`: ein CLI darf blockieren
# (deshalb ist `_pipe.py` synchron), ein async Test nicht.


def _tools_present() -> bool:
    return all(shutil.which(t) for t in ("pg_dump", "age", "age-keygen"))


@pytest.fixture(scope="module")
def recipient(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Nur der öffentliche Teil — mehr braucht das Sichern nie."""
    if not _tools_present():
        pytest.skip("pg_dump/age/age-keygen nicht installiert")
    identity = tmp_path_factory.mktemp("age") / "identity.txt"
    keygen = shutil.which("age-keygen") or "age-keygen"
    proc = subprocess.run(  # noqa: S603 — feste Argumente dieses Tests
        [keygen, "-o", str(identity)], capture_output=True, text=True, check=True
    )
    for line in (proc.stderr or "").splitlines():
        if "public key:" in line.lower():
            return line.split(":", 1)[1].strip()
    raise AssertionError("age-keygen hat keinen öffentlichen Schlüssel gemeldet")


def _tenant(database_url: str) -> Tenant:
    """Der Mandant, den die Integrationsumgebung tatsächlich hat: `public`."""
    return Tenant(
        slug="testkunde",
        name="Testkunde",
        dsn=database_url,
        schema_name="public",
        db_role=None,
        schema_version="",
        status=TenantStatus.ACTIVE,
    )


@pytest.mark.usefixtures("engine")
class TestDumpIsEncrypted:
    @pytest.mark.asyncio
    async def test_the_dump_is_age_encrypted_and_has_no_plaintext(
        self, database_url: str, recipient: str, tmp_path: Path
    ) -> None:
        step = await asyncio.to_thread(
            dump_tenant, _tenant(database_url), tmp_path, recipient=recipient
        )
        assert step.ok, step.detail

        written = await asyncio.to_thread(lambda: list(tmp_path.iterdir()))
        assert len(written) == 1, f"erwartet genau eine Datei, gefunden: {written}"
        dump = written[0]
        assert dump.name.endswith(".dump.age")

        payload = await asyncio.to_thread(dump.read_bytes)
        head = payload[:64]
        # age schreibt einen Textkopf; ein pg_dump im custom-Format beginnt mit
        # "PGDMP". Beides zugleich wäre ein Widerspruch — genau den prüfen wir.
        assert head.startswith(b"age-encryption.org/"), head[:32]
        assert b"PGDMP" not in payload[:4096]

    @pytest.mark.asyncio
    async def test_no_plaintext_file_is_left_behind(
        self, database_url: str, recipient: str, tmp_path: Path
    ) -> None:
        """Auch keine Zwischendatei und kein `.partial`.

        Das ist der Grund für die Kette ohne Zwischendatei: eine
        unverschlüsselte Datei, die nur „kurz“ existiert, existiert nach einem
        Abbruch weiter.
        """
        await asyncio.to_thread(dump_tenant, _tenant(database_url), tmp_path, recipient=recipient)
        names = await asyncio.to_thread(lambda: [p.name for p in tmp_path.iterdir()])
        assert not [n for n in names if n.endswith(".partial")]
        assert all(n.endswith(".dump.age") for n in names), names

    @pytest.mark.asyncio
    async def test_the_dump_restores(
        self, database_url: str, recipient: str, tmp_path: Path
    ) -> None:
        """Verschlüsselt **und** brauchbar.

        Ein Dump, der sich nicht einspielen lässt, ist keine Rückfahrkarte.
        Geprüft wird nur, dass ``pg_restore --list`` den Inhalt liest —
        einspielen tut es der Wiederherstellungsweg (`cli/backup.py`), und der
        hat seinen eigenen Test.
        """
        identity_dir = tmp_path / "keys"
        await asyncio.to_thread(identity_dir.mkdir)
        identity = identity_dir / "identity.txt"
        keygen = shutil.which("age-keygen") or "age-keygen"
        proc = await asyncio.to_thread(
            lambda: subprocess.run(  # noqa: S603
                [keygen, "-o", str(identity)], capture_output=True, text=True, check=True
            )
        )
        own_recipient = next(
            line.split(":", 1)[1].strip()
            for line in (proc.stderr or "").splitlines()
            if "public key:" in line.lower()
        )
        target = tmp_path / "dumps"
        step = await asyncio.to_thread(
            dump_tenant, _tenant(database_url), target, recipient=own_recipient
        )
        assert step.ok, step.detail
        dump = await asyncio.to_thread(lambda: next(target.iterdir()))

        decrypted = await asyncio.to_thread(
            lambda: subprocess.run(  # noqa: S603
                [shutil.which("age") or "age", "-d", "-i", str(identity), str(dump)],
                capture_output=True,
                check=True,
            )
        )
        listing = await asyncio.to_thread(
            lambda: subprocess.run(  # noqa: S603
                [shutil.which("pg_restore") or "pg_restore", "--list"],
                input=decrypted.stdout,
                capture_output=True,
                check=True,
            )
        )
        assert b"TABLE DATA" in listing.stdout or b"TABLE" in listing.stdout


class TestRefusals:
    def test_without_a_recipient_there_is_no_dump(self, tmp_path: Path) -> None:
        with pytest.raises(PipeError) as exc:
            check_recipient(None)
        assert RECIPIENT_ENV in str(exc.value)

    def test_a_malformed_recipient_is_refused(self) -> None:
        # Ein Tippfehler im Schlüssel darf nicht in einem Klartext-Dump enden.
        for bad in ("", "age1", "not-a-key", "AGE1" + "a" * 58):
            with pytest.raises(PipeError):
                check_recipient(bad)

    def test_a_missing_recipient_fails_the_step_not_the_run(
        self, database_url: str, tmp_path: Path
    ) -> None:
        """Kein Absturz, sondern ein gescheiterter Schritt mit Begründung.

        Der Aufrufer hält danach die Migration an — ohne Dump wird nicht
        migriert. Ein `raise` bis nach oben hätte denselben Effekt und eine
        schlechtere Meldung.
        """
        step = dump_tenant(_tenant(database_url), tmp_path, recipient="unbrauchbar")
        assert not step.ok
        assert RECIPIENT_ENV in step.detail
        assert not list(tmp_path.iterdir())
