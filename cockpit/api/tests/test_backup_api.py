"""Die Endpunkte um Sicherung, Aufbewahrung, Wiederherstellung, Export (ADR-0016).

Was hier geprüft wird, ist vor allem **wer was darf und in welcher
Reihenfolge**. Die Konsole kann sichern und exportieren; wiederherstellen und
prüfen kann sie nicht, weil der private Backup-Schlüssel nicht auf dem
Anwendungsserver liegt (D2). Ihre Endpunkte dafür erfassen einen Auftrag und
nehmen ein Ergebnis entgegen — und genau das soll auch so bleiben, wenn jemand
später „nur schnell" einen Auslöse-Endpunkt dazubauen will.

Dazu die Freigabe durch eine zweite Person (D5) und die Frist auf dem
Export-Download (D7): ein Link, der ewig gilt, ist ein Datenleck mit
Verfallsdatum „nie".
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings
from cockpit_api.models import BackupKind, BackupStatus, TenantBackupPolicy
from cockpit_api.services.backup_policy import COUNTS_AS_PRESENT, keep_for, resolve_kind

SLUG = "apitest"


def _tools_present() -> bool:
    return all(shutil.which(t) for t in ("pg_dump", "pg_restore", "age", "age-keygen"))


@pytest.fixture
def backup_config(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """Share, Exportverzeichnis und ein age-Schlüsselpaar für diesen Test."""
    if not _tools_present():
        pytest.skip("pg_dump/pg_restore/age/age-keygen nicht installiert")
    identity = tmp_path / "identity.txt"
    keygen = shutil.which("age-keygen") or "age-keygen"
    proc = subprocess.run(  # noqa: S603 — feste Argumente dieses Tests
        [keygen, "-o", str(identity)], capture_output=True, text=True, check=True
    )
    recipient = ""
    for line in (proc.stderr or "").splitlines():
        if "public key:" in line.lower():
            recipient = line.split(":", 1)[1].strip()
    assert recipient

    share = tmp_path / "share"
    exports = tmp_path / "exports"
    share.mkdir()
    exports.mkdir()
    previous = (
        settings.backup_share_root,
        settings.backup_age_recipient,
        settings.export_root,
        settings.export_ttl_days,
    )
    settings.backup_share_root = str(share)
    settings.backup_age_recipient = recipient
    settings.export_root = str(exports)
    settings.export_ttl_days = 7
    yield share, exports
    (
        settings.backup_share_root,
        settings.backup_age_recipient,
        settings.export_root,
        settings.export_ttl_days,
    ) = previous


@pytest.fixture
def tenant_id(db_client: TestClient, magister_admin_dsn: str) -> str:
    """Einen echten Kunden bereitstellen und vorher aufräumen."""
    import asyncio

    if not settings.magister_api_dir:
        pytest.skip("COCKPIT_TEST_MAGISTER_API_DIR nicht gesetzt")

    async def clean() -> None:
        engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS t_{SLUG} CASCADE")
            async with engine.begin() as conn:
                found = (
                    await conn.execute(
                        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": f"r_{SLUG}"}
                    )
                ).scalar()
                if found:
                    await conn.exec_driver_sql(f"DROP OWNED BY r_{SLUG} CASCADE")
                    await conn.exec_driver_sql(f"DROP ROLE r_{SLUG}")
        finally:
            await engine.dispose()

    asyncio.run(clean())
    created = db_client.post(
        "/api/tenants",
        json={"slug": SLUG, "name": "API-Stadt", "hostname": f"{SLUG}.magister.test"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["tenant"]["id"])


@pytest.mark.usefixtures("cockpit_schema")
class TestBackups:
    def test_a_backup_is_written_and_recorded(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        share, _ = backup_config
        resp = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "written", body.get("error")
        assert body["checksum_sha256"]
        assert body["size_bytes"] > 0
        # Die Zeile trägt den Schlüsselverweis: wer wiederherstellt, sucht
        # damit den passenden Kundenschlüssel (ADR-0016 D2).
        assert body["audit_key_id"] == f"{SLUG}-v1"
        assert body["schema_version"]
        # Und die Datei liegt verschlüsselt auf dem Share.
        written = Path(body["path"])
        assert written.is_file()
        assert written.parent == share / SLUG
        assert b"age-encryption.org" in written.read_bytes()[:200]
        assert b"PGDMP" not in written.read_bytes()

        listed = db_client.get(f"/api/tenants/{tenant_id}/backups").json()
        assert [row["id"] for row in listed] == [body["id"]]

    def test_a_missing_recipient_refuses_instead_of_writing_plaintext(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """Kein öffentlicher Schlüssel heisst: keine Sicherung. Nicht: eine offene."""
        share, _ = backup_config
        settings.backup_age_recipient = ""
        resp = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "manual"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert "age-Schlüssel" in body["error"]
        # Und es liegt nichts da.
        assert not list((share / SLUG).glob("*")) if (share / SLUG).exists() else True

    def test_the_console_reports_a_verification_it_did_not_perform(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """``verified_at`` setzt nur eine gemeldete, geglückte Prüfung.

        Prüfen kann die Konsole nicht — dazu bräuchte sie den privaten
        Schlüssel. Sie tut auch nicht so.
        """
        created = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"}).json()
        assert created["verified_at"] is None

        ok = db_client.post(
            f"/api/backups/{created['id']}/verify-result",
            params={"ok": True, "detail": "27 Tabellen, Alembic 0044, Payloads verschlüsselt"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["verified_at"] is not None
        assert ok.json()["status"] == "verified"

        bad = db_client.post(
            f"/api/backups/{created['id']}/verify-result",
            params={"ok": False, "detail": "Tabellen fehlen: classes"},
        )
        assert bad.json()["status"] == "failed"
        assert "classes" in bad.json()["error"]


@pytest.mark.usefixtures("cockpit_schema")
class TestPolicy:
    def test_defaults_are_visible_without_a_row(
        self, db_client: TestClient, tenant_id: str
    ) -> None:
        """Ein Kunde ohne eigene Zeile hat trotzdem eine Frist, und die soll man sehen."""
        resp = db_client.get(f"/api/tenants/{tenant_id}/backup-policy")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Entscheid E14: 10 Tage, und 30 für Vor-Migrations-Dumps (D6).
        assert body["retention_days"] == 10
        assert body["pre_migration_retention_days"] == 30

    def test_contract_values_can_be_changed(self, db_client: TestClient, tenant_id: str) -> None:
        resp = db_client.put(
            f"/api/tenants/{tenant_id}/backup-policy",
            json={"retention_days": 30, "rto_hours": 4},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["retention_days"] == 30
        assert resp.json()["rto_hours"] == 4
        # Nicht gesetzte Felder bleiben stehen.
        assert resp.json()["pre_migration_retention_days"] == 30

    def test_a_zero_retention_is_refused(self, db_client: TestClient, tenant_id: str) -> None:
        """Unter einem Tag gibt es keine sinnvolle Wiederherstellungszusage."""
        resp = db_client.put(f"/api/tenants/{tenant_id}/backup-policy", json={"retention_days": 0})
        assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("cockpit_schema")
class TestRestoreJobs:
    def _backup(self, db_client: TestClient, tenant_id: str) -> str:
        created = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"}).json()
        assert created["status"] == "written", created.get("error")
        return str(created["id"])

    def test_a_restore_needs_a_reason(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        backup_id = self._backup(db_client, tenant_id)
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/restore-jobs",
            json={"backup_id": backup_id, "reason": "", "requested_by": "matthias"},
        )
        assert resp.status_code == 422, resp.text

    def test_switching_needs_a_second_person(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """ADR-0016 D5. Und die Reihenfolge stimmt auch: erst eingespielt, dann freigegeben."""
        backup_id = self._backup(db_client, tenant_id)
        job = db_client.post(
            f"/api/tenants/{tenant_id}/restore-jobs",
            json={
                "backup_id": backup_id,
                "reason": "Ticket VB-4711",
                "requested_by": "matthias",
            },
        ).json()
        job_id = job["id"]
        assert job["state"] == "requested"
        assert job["target_schema"].startswith("r_apitest_")

        # Freigabe vor dem Einspielen: eine Freigabe für etwas, das noch nicht
        # existiert, ist keine.
        early = db_client.post(f"/api/restore-jobs/{job_id}/approve", json={"approved_by": "rolf"})
        assert early.status_code == 409, early.text

        # Der Backup-Host meldet das Ergebnis.
        reported = db_client.post(f"/api/restore-jobs/{job_id}/report", params={"ok": True})
        assert reported.json()["state"] == "restored"

        # Dieselbe Person darf nicht freigeben.
        same = db_client.post(
            f"/api/restore-jobs/{job_id}/approve", json={"approved_by": "Matthias"}
        )
        assert same.status_code == 409, same.text
        assert "verschieden" in same.json()["detail"]

        # Und ohne Freigabe wird nicht umgeschaltet.
        unapproved = db_client.post(f"/api/restore-jobs/{job_id}/switched")
        assert unapproved.status_code == 409, unapproved.text

        approved = db_client.post(
            f"/api/restore-jobs/{job_id}/approve", json={"approved_by": "rolf"}
        )
        assert approved.status_code == 200, approved.text

        switched = db_client.post(f"/api/restore-jobs/{job_id}/switched")
        assert switched.status_code == 200, switched.text
        body = switched.json()
        assert body["state"] == "switched"
        # Das verdrängte Schema bleibt vermerkt — der Rückweg.
        assert body["previous_schema"] == f"t_{SLUG}"

    def test_a_failed_restore_is_recorded_as_failed(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        backup_id = self._backup(db_client, tenant_id)
        job_id = db_client.post(
            f"/api/tenants/{tenant_id}/restore-jobs",
            json={"backup_id": backup_id, "reason": "Probe", "requested_by": "matthias"},
        ).json()["id"]
        resp = db_client.post(
            f"/api/restore-jobs/{job_id}/report",
            params={"ok": False, "detail": "pg_restore: Fehler in Zeile 12"},
        )
        assert resp.json()["state"] == "failed"
        assert "Zeile 12" in resp.json()["error"]


@pytest.mark.usefixtures("cockpit_schema")
class TestExports:
    def test_an_export_can_be_created_and_downloaded_once_within_the_window(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/exports", json={"requested_by": "matthias"}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["state"] == "ready", body.get("error")
        assert body["checksum_sha256"]
        assert body["expires_at"]

        download = db_client.get(f"/api/exports/{body['id']}/download")
        assert download.status_code == 200, download.text
        assert download.headers["content-type"] == "application/zip"

        # Ein zweites Mal geht weiter — der Zustand ist jetzt „downloaded",
        # nicht „verbraucht". Ein Kunde, dem der Browser abbricht, soll nicht
        # neu bestellen müssen.
        again = db_client.get(f"/api/exports/{body['id']}/download")
        assert again.status_code == 200
        assert db_client.get(f"/api/tenants/{tenant_id}/exports").json()[0]["state"] == (
            "downloaded"
        )

    def test_the_downloaded_archive_is_a_readable_zip(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """Ohne Magister lesbar heisst: mit ``zipfile`` aus der Standardbibliothek."""
        body = db_client.post(
            f"/api/tenants/{tenant_id}/exports", json={"requested_by": "matthias"}
        ).json()
        with zipfile.ZipFile(Path(body["path"])) as archive:
            names = set(archive.namelist())
        assert "MANIFEST.json" in names
        assert "README.txt" in names
        assert "daten/schools.csv" in names

    def test_an_expired_download_is_gone_not_served(
        self,
        db_client: TestClient,
        tenant_id: str,
        backup_config: tuple[Path, Path],
        cockpit_schema: str,
    ) -> None:
        """Ein Link, der ewig gilt, ist ein Datenleck mit Verfallsdatum „nie“."""
        import asyncio

        body = db_client.post(
            f"/api/tenants/{tenant_id}/exports", json={"requested_by": "matthias"}
        ).json()

        async def expire() -> None:
            # Der DSN kommt aus der Fixture, nicht aus ``settings``: die Tests
            # hängen die Sitzung auf die Testdatenbank um, ``database_url``
            # zeigt weiter auf die Vorgabe.
            engine = create_async_engine(cockpit_schema, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE export_jobs SET expires_at = :t WHERE id = :i"),
                        {"t": datetime.now(UTC) - timedelta(seconds=1), "i": body["id"]},
                    )
            finally:
                await engine.dispose()

        asyncio.run(expire())
        resp = db_client.get(f"/api/exports/{body['id']}/download")
        assert resp.status_code == 410, resp.text
        assert db_client.get(f"/api/tenants/{tenant_id}/exports").json()[0]["state"] == "expired"


class TestMonthlyCopiesPureLogic:
    """Wann eine tägliche Sicherung zur Monatskopie wird (Entscheid E15).

    Zehn Tage (E14) decken zwei Fälle nicht ab, und beide sind bei Schulen
    realistisch: ein Fehler, der erst am Quartalsende auffällt, und ein
    Trojaner, der Wochen im Netz sass. Deshalb zwölf Monatskopien — aber ohne
    zweiten Dump: die erste geglückte Sicherung des Monats wird *als*
    Monatskopie geschrieben.
    """

    def _policy(self, **over: object) -> TenantBackupPolicy:
        row = TenantBackupPolicy(tenant_id=uuid.uuid4())
        row.retention_days = 10
        row.pre_migration_retention_days = 30
        row.monthly_enabled = True
        row.monthly_keep = 12
        for key, value in over.items():
            setattr(row, key, value)
        return row

    def test_the_first_daily_of_a_month_becomes_the_monthly_copy(self) -> None:
        assert (
            resolve_kind(BackupKind.daily, policy=self._policy(), monthly_present=False)
            is BackupKind.monthly
        )

    def test_later_dailies_stay_daily(self) -> None:
        assert (
            resolve_kind(BackupKind.daily, policy=self._policy(), monthly_present=True)
            is BackupKind.daily
        )

    @pytest.mark.parametrize(
        "kind",
        [BackupKind.manual, BackupKind.pre_migration, BackupKind.offboarding],
    )
    def test_only_a_daily_is_promoted(self, kind: BackupKind) -> None:
        """Sonst hätte ein Handgriff plötzlich eine Zwölfmonatsfrist.

        Und eine Vor-Migrations-Sicherung hat ihre eigene Frist aus D6; sie zur
        Monatskopie zu machen würde die eine Frist durch die andere ersetzen.
        """
        assert resolve_kind(kind, policy=self._policy(), monthly_present=False) is kind

    def test_it_can_be_switched_off_per_tenant(self) -> None:
        """Es ist eine Vertragsfrage — mit Folgen, die im ADR stehen."""
        assert (
            resolve_kind(
                BackupKind.daily,
                policy=self._policy(monthly_enabled=False),
                monthly_present=False,
            )
            is BackupKind.daily
        )

    def test_without_a_policy_row_the_default_applies(self) -> None:
        """E15 ist entschieden, also gilt es auch ohne eigene Zeile."""
        assert (
            resolve_kind(BackupKind.daily, policy=None, monthly_present=False) is BackupKind.monthly
        )

    def test_the_retention_is_named_in_words(self) -> None:
        policy = self._policy()
        assert keep_for(BackupKind.monthly, policy) == "die letzten 12 Monatskopien"
        assert keep_for(BackupKind.daily, policy) == "10 Tage"
        assert keep_for(BackupKind.pre_migration, policy) == "30 Tage"

    def test_a_running_backup_does_not_count_as_present(self) -> None:
        """Ein Lauf, der noch nicht fertig ist, kann scheitern.

        Zählte er mit, hätte der Monat keine Kopie und niemand würde es
        nachholen — eine Lücke, die erst auffällt, wenn sie gebraucht wird.
        """
        assert BackupStatus.running not in COUNTS_AS_PRESENT
        assert BackupStatus.failed not in COUNTS_AS_PRESENT
        assert BackupStatus.written in COUNTS_AS_PRESENT
        assert BackupStatus.verified in COUNTS_AS_PRESENT


@pytest.mark.usefixtures("cockpit_schema")
class TestMonthlyCopies:
    def test_the_first_backup_of_the_month_is_a_monthly_copy(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """Die Cron-Zeile schickt weiter `daily`; die Konsole entscheidet."""
        first = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        assert first.status_code == 201, first.text
        assert first.json()["kind"] == "monthly", "die erste des Monats wird befördert"
        assert first.json()["status"] == "written"

        second = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        assert second.json()["kind"] == "daily", "die zweite bleibt täglich"

    def test_only_one_dump_is_written_not_two(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """Kein zusätzlicher Lauf am Monatsersten: derselbe Dump, andere Frist."""
        share, _ = backup_config
        db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        files = sorted((share / SLUG).glob("*.dump.age"))
        assert len(files) == 1
        assert files[0].name.endswith("-monthly.dump.age")

    def test_a_failed_monthly_is_retried_the_next_day(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """Entschieden wird „gibt es eine", nicht „ist heute der Erste".

        Scheitert die Sicherung am 1., wird die vom 2. zur Monatskopie. Ein
        Monat ohne Kopie wäre eine Lücke, die niemandem auffällt.
        """
        settings.backup_age_recipient = ""
        failed = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        assert failed.json()["status"] == "failed"
        # Auch die gescheiterte trug schon `monthly` — sie zählt aber nicht.
        _, exports = backup_config
        settings.backup_age_recipient = _recipient(exports)

        again = db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        assert again.json()["status"] == "written"
        assert again.json()["kind"] == "monthly", "der gescheiterte Lauf zählt nicht"

    def test_the_retention_hint_lands_next_to_the_dumps(
        self, db_client: TestClient, tenant_id: str, backup_config: tuple[Path, Path]
    ) -> None:
        """Der Aufräumjob läuft auf dem Fileserver und hat keinen Konsolenzugang.

        Ohne diese Datei müsste er die Fristen raten — und ein Kunde mit 30
        Tagen Zusage, dessen Dumps nach 10 gelöscht werden, ist ein
        Vertragsbruch, den niemand bemerkt.
        """
        share, _ = backup_config
        db_client.put(
            f"/api/tenants/{tenant_id}/backup-policy",
            json={"retention_days": 30, "monthly_keep": 6},
        )
        db_client.post(f"/api/tenants/{tenant_id}/backups", json={"kind": "daily"})
        hint = (share / SLUG / ".retention").read_text(encoding="utf-8")
        assert "retention_days=30" in hint
        assert "monthly_keep=6" in hint
        # Kein Geheimnis darin.
        assert "age1" not in hint and "postgres" not in hint

    def test_the_policy_exposes_the_monthly_settings(
        self, db_client: TestClient, tenant_id: str
    ) -> None:
        body = db_client.get(f"/api/tenants/{tenant_id}/backup-policy").json()
        assert body["monthly_enabled"] is True
        assert body["monthly_keep"] == 12

    def test_zero_monthly_copies_is_not_reachable_by_a_number(
        self, db_client: TestClient, tenant_id: str
    ) -> None:
        """„Keine Monatskopien" heisst monthly_enabled=false, nicht keep=0.

        Zwei Wege zum selben Zustand sind zwei Wege, ihn versehentlich zu
        erreichen.
        """
        resp = db_client.put(f"/api/tenants/{tenant_id}/backup-policy", json={"monthly_keep": 0})
        assert resp.status_code == 422


@pytest.mark.usefixtures("cockpit_schema")
class TestOffboardingKeepsItsDeletionPromise:
    """E15 hätte die Löschzusage aus D8 unwahr gemacht.

    „Zehn Tage nach dem Crypto-Shredding ist auch der Rest weg" — mit zwölf
    Monatskopien läge eine Kopie von vor elf Monaten an diesem Datum noch auf
    dem Share. Löschen darf die Konsole nicht (D2: kein Löschrecht, damit ein
    übernommener Anwendungsserver die Sicherungen nicht mitnehmen kann), also
    schreibt sie dem Aufräumjob eine Markierung.
    """

    def test_the_marker_is_written_with_the_purge_date(
        self,
        db_client: TestClient,
        tenant_id: str,
        backup_config: tuple[Path, Path],
        cockpit_schema: str,
    ) -> None:
        share, _ = backup_config
        # Der DSN kommt aus der Fixture, nicht aus settings: die Tests hängen
        # die Sitzung auf die Testdatenbank um.
        _run_offboarding_to_shredding(db_client, tenant_id, cockpit_dsn=cockpit_schema)
        marker = share / SLUG / ".offboarding"
        assert marker.is_file(), "ohne die Markierung bleibt die Zusage unerfüllt"
        text = marker.read_text(encoding="utf-8")
        assert f"slug={SLUG}" in text
        assert "purge_due_at=" in text
        # Ein Auftrag zum Löschen, kein Zugang.
        assert "api_key" not in text and "age1" not in text

    def test_without_a_share_the_answer_says_so(
        self,
        db_client: TestClient,
        tenant_id: str,
        backup_config: tuple[Path, Path],
        cockpit_schema: str,
    ) -> None:
        """Der Schlüssel ist vernichtet — unwiderruflich. Also kein Rollback.

        Aber die Antwort muss sagen, dass eine Frist läuft, die niemand
        einhält, statt es in einer Protokollzeile untergehen zu lassen.
        """
        settings.backup_share_root = ""
        body = _run_offboarding_to_shredding(db_client, tenant_id, cockpit_dsn=cockpit_schema)
        assert body["state"] == "shredded", "der Schritt selbst gilt"
        assert body["warning"], "die Antwort muss die offene Frist nennen"
        assert "Monatskopien" in body["warning"]


def _recipient(directory: Path) -> str:
    """Den öffentlichen age-Schlüssel aus der Fixture wiederfinden."""
    return settings.backup_age_recipient or _regenerate(directory)


def _regenerate(directory: Path) -> str:
    keygen = shutil.which("age-keygen") or "age-keygen"
    identity = directory / "wieder-identity.txt"
    proc = subprocess.run(  # noqa: S603
        [keygen, "-o", str(identity)], capture_output=True, text=True, check=True
    )
    for line in (proc.stderr or "").splitlines():
        if "public key:" in line.lower():
            return line.split(":", 1)[1].strip()
    raise AssertionError("age-keygen hat keinen Schlüssel gemeldet")


def _run_offboarding_to_shredding(
    client: TestClient, tenant_id: str, *, cockpit_dsn: str
) -> dict[str, Any]:
    """Offboarding bis zur Bestätigung des Crypto-Shreddings durchspielen."""
    started = client.post(
        f"/api/tenants/{tenant_id}/offboarding",
        json={"reason": "Kündigung, Test", "requested_by": "matthias", "grace_days": 0},
    )
    assert started.status_code == 201, started.text
    export_id = _insert_ready_export(cockpit_dsn, tenant_id)
    assert (
        client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}").status_code == 200
    )
    dropped = client.post(
        f"/api/tenants/{tenant_id}/offboarding/drop",
        json={"dropped_by": "matthias", "approved_by": "rolf"},
    )
    assert dropped.status_code == 200, dropped.text
    shredded = client.post(
        f"/api/tenants/{tenant_id}/offboarding/key-destroyed",
        json={"confirmed_by": "matthias"},
    )
    assert shredded.status_code == 200, shredded.text
    body: dict[str, Any] = shredded.json()
    return body


def _insert_ready_export(cockpit_dsn: str, tenant_id: str) -> str:
    import asyncio
    import uuid as _uuid

    export_id = _uuid.uuid4()

    async def insert() -> None:
        engine = create_async_engine(cockpit_dsn, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO export_jobs (id, tenant_id, state, requested_by, "
                        "path, size_bytes, expires_at) VALUES "
                        "(:i, :t, 'ready', 'matthias', '/tmp/kein-echter-export.zip', 1, :e)"
                    ),
                    {
                        "i": export_id,
                        "t": _uuid.UUID(tenant_id),
                        "e": datetime.now(UTC) + timedelta(days=7),
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    return str(export_id)
