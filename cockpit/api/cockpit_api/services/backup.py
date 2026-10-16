"""Sicherung pro Kunde: dumpen, verschlüsseln, buchen (ADR-0016 D1, D2).

Der Weg ist bewusst eine Kette von zwei Prozessen ohne Zwischendatei:

    pg_dump --schema=t_<slug>  →  age -r <öffentlicher Schlüssel>  →  Share

**Ohne Zwischendatei**, weil eine unverschlüsselte Zwischendatei auf dem
Anwendungsserver genau das Ding ist, das man vermeiden will — und sie liegt
dort auch dann noch, wenn der Prozess mittendrin abbricht.

Verschlüsselt wird mit dem **öffentlichen** Plattform-Backup-Schlüssel. Der
Sicherungsprozess kann damit schreiben, aber nichts lesen: wer den
Anwendungsserver übernimmt, bekommt keine alten Sicherungen entschlüsselt.
Der private Schlüssel liegt getrennt und wird hier nie gebraucht.

Die Prüfsumme geht über die **verschlüsselte** Datei. Damit lässt sich später
feststellen, ob der Share sie unverändert hält, ohne sie entschlüsseln zu
müssen — und ein beschädigter Dump ist dann *beschädigt* und nicht bloss
*unlesbar*.

Die beiden Prozesse laufen über ``pgtools.run_chain`` in einem Thread — die
Begründung (Event-Loop, stderr-Verklemmung) steht dort.

Was dieses Modul **nicht** tut: löschen. Das Dienstkonto hat auf dem Share
keine Löschrechte; das Aufräumen läuft als eigener Cron-Job mit eigenem Konto
auf dem Fileserver (ADR-0016 D2, Entscheid E13). Ein übernommener
Anwendungsserver kann die Sicherungen damit nicht mitnehmen.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cockpit_api.services.pgtools import Stage, ToolError, libpq_env, run_chain

logger = logging.getLogger(__name__)

#: Öffentlicher age-Schlüssel: ``age1`` plus Bech32.
RECIPIENT_PATTERN = re.compile(r"^age1[0-9a-z]{58}$")

#: Bezeichner, die in einen Pfad oder ein Kommando gehen.
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class BackupError(RuntimeError):
    """Die Sicherung ist gescheitert. Nichts Halbes bleibt liegen."""


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    path: Path
    size_bytes: int
    checksum_sha256: str


def check_recipient(recipient: str) -> str:
    """Öffentlichen Schlüssel prüfen.

    Ein leerer oder falsch geformter Empfänger wäre der Weg zu einer
    **unverschlüsselten** Sicherung — deshalb Abbruch und keine Warnung. Auf
    einem Share sind die Dumps für mehr Personen und Systeme erreichbar als in
    der Datenbank.
    """
    value = recipient.strip()
    if not RECIPIENT_PATTERN.match(value):
        raise BackupError(
            "COCKPIT_BACKUP_AGE_RECIPIENT ist kein gültiger öffentlicher "
            "age-Schlüssel (erwartet 'age1…'). Ohne ihn würde unverschlüsselt "
            "auf den Share geschrieben — das wird nicht gemacht."
        )
    return value


def backup_path(share_root: Path, slug: str, kind: str, when: datetime) -> Path:
    """Ablagepfad: ein Verzeichnis je Kunde, Dateiname mit Art und Zeit."""
    if not IDENTIFIER_PATTERN.match(slug):
        raise BackupError(f"slug={slug!r} ist kein zulässiger Bezeichner.")
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    return share_root / slug / f"{slug}-{stamp}-{kind}.dump.age"


async def create_backup(
    *,
    dsn: str,
    schema_name: str,
    slug: str,
    kind: str,
    share_root: Path,
    recipient: str,
    when: datetime | None = None,
) -> BackupArtifact:
    """Dump ziehen, verschlüsselt ablegen, Prüfsumme bilden."""
    if not IDENTIFIER_PATTERN.match(schema_name):
        raise BackupError(f"schema_name={schema_name!r} ist kein zulässiger Bezeichner.")
    check_recipient(recipient)
    for tool in ("pg_dump", "age"):
        if shutil.which(tool) is None:
            raise BackupError(
                f"{tool} ist nicht installiert. Ohne {tool} gibt es keine "
                "verschlüsselte Sicherung, und eine unverschlüsselte wird nicht "
                "geschrieben."
            )

    target = backup_path(share_root, slug, kind, when or datetime.now(UTC))
    target.parent.mkdir(parents=True, exist_ok=True)
    # Erst unter einem Arbeitsnamen schreiben, dann umbenennen: sonst liegt bei
    # einem Abbruch eine halbe Datei da, die aussieht wie eine Sicherung.
    partial = target.with_suffix(target.suffix + ".partial")

    try:
        await run_chain(
            Stage(
                argv=(
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    f"--schema={schema_name}",
                ),
                env=libpq_env(dsn),
                label="pg_dump",
            ),
            Stage(argv=("age", "-r", recipient, "-o", str(partial)), label="age"),
        )
    except ToolError as exc:
        partial.unlink(missing_ok=True)
        raise BackupError(f"Sicherung gescheitert: {exc}") from exc

    size = partial.stat().st_size
    if size == 0:
        partial.unlink(missing_ok=True)
        raise BackupError("Die Sicherung ist leer.")

    digest = _sha256(partial)
    partial.replace(target)
    logger.info("Sicherung für %s geschrieben: %s (%d Bytes)", slug, target.name, size)
    return BackupArtifact(path=target, size_bytes=size, checksum_sha256=digest)


#: Name der Markierung, mit der die Konsole dem Aufräumjob mitteilt, dass für
#: diesen Kunden die kurze Frist gilt.
OFFBOARDING_MARKER = ".offboarding"

#: Name der Datei, in der die Aufbewahrung dieses Kunden steht.
RETENTION_HINT = ".retention"


def write_retention_hint(
    share_root: Path,
    slug: str,
    *,
    retention_days: int,
    pre_migration_retention_days: int,
    monthly_keep: int,
) -> Path:
    """Die Aufbewahrung dieses Kunden neben seine Dumps schreiben.

    Der Aufräumjob läuft auf dem **Fileserver** mit eigenem Konto (ADR-0016
    D2) und hat keinen Zugang zur Konsole. Er müsste die Fristen also aus
    Vorgabewerten raten — und läge falsch, sobald ein Kunde eine
    Vertragsabweichung hat. Ein Kunde mit 30 Tagen Zusage, dessen Dumps nach
    10 Tagen gelöscht werden, ist ein Vertragsbruch, den niemand bemerkt,
    bis er gebraucht wird.

    Die Alternative wäre gewesen, dem Aufräumjob Zugangsdaten für die
    Konsolen-API zu geben — für eine Auskunft, die in drei Zeilen passt. Nicht
    dafür. Geschrieben wird bei jeder Sicherung, also ist die Datei immer
    aktuell, und sie enthält kein Geheimnis.
    """
    if not IDENTIFIER_PATTERN.match(slug):
        raise BackupError(f"slug={slug!r} ist kein zulässiger Bezeichner.")
    directory = share_root / slug
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / RETENTION_HINT
    target.write_text(
        "# Aufbewahrung dieses Kunden. Von der Konsole geschrieben, von\n"
        "# prune-backups.sh gelesen. Kein Geheimnis.\n"
        f"retention_days={retention_days}\n"
        f"pre_migration_retention_days={pre_migration_retention_days}\n"
        f"monthly_keep={monthly_keep}\n",
        encoding="utf-8",
    )
    return target


def write_offboarding_marker(
    share_root: Path, slug: str, *, purge_due_at: datetime, key_id: str | None
) -> Path:
    """Dem Aufräumjob sagen, dass dieser Kunde offboardet ist (E15, D8).

    **Warum das nötig ist, und warum als Datei.** Mit zwölf Monatskopien (E15)
    wäre die Löschzusage aus D8 unwahr: „zehn Tage nach dem Crypto-Shredding
    ist auch der Rest weg" — eine Monatskopie kann elf Monate alt sein und
    läge an diesem Datum noch da. Für einen gekündigten Kunden muss die kurze
    Frist also auch für die Monatskopien gelten.

    Löschen darf die Konsole nicht: das Dienstkonto hat auf dem Share
    ausdrücklich kein Löschrecht, damit ein übernommener Anwendungsserver die
    Sicherungen nicht mitnehmen kann (ADR-0016 D2). Sie kann aber
    **schreiben** — sie schreibt ja die Dumps. Eine Markierung im
    Kundenverzeichnis ist deshalb der Weg, der ohne neue Rechte und ohne
    zweiten Zugang auskommt: der Aufräumjob auf dem Fileserver liest sie und
    wendet die kurze Frist an.

    Die Alternative wäre gewesen, dem Aufräumjob Zugang zur Konsolen-API zu
    geben. Das hiesse: Zugangsdaten für die Konsole auf dem Fileserver, für
    eine Auskunft, die in eine Zeile passt. Nicht dafür.

    Die Datei enthält kein Geheimnis — Datum, Slug und die Id des vernichteten
    Schlüssels. Sie ist ein Auftrag zum Löschen, kein Zugang.
    """
    if not IDENTIFIER_PATTERN.match(slug):
        raise BackupError(f"slug={slug!r} ist kein zulässiger Bezeichner.")
    directory = share_root / slug
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / OFFBOARDING_MARKER
    target.write_text(
        "# Dieser Kunde ist offboardet (ADR-0016 D8).\n"
        "# Fuer ALLE Sicherungen dieses Verzeichnisses gilt ab jetzt die kurze\n"
        "# Frist, auch fuer die Monatskopien. prune-backups.sh liest diese Datei.\n"
        f"slug={slug}\n"
        f"purge_due_at={purge_due_at.isoformat()}\n"
        f"key_id={key_id or ''}\n"
        f"written_at={datetime.now(UTC).isoformat()}\n",
        encoding="utf-8",
    )
    logger.info(
        "Offboarding-Markierung für %s geschrieben: %s (Frist %s)",
        slug,
        target,
        purge_due_at.isoformat(),
    )
    return target


def verify_checksum(path: Path, expected: str) -> bool:
    """Prüfsumme der verschlüsselten Datei nachrechnen.

    Ohne Entschlüsselung, also ohne den privaten Schlüssel. Damit lässt sich
    täglich prüfen, ob der Share die Datei unverändert hält — die inhaltliche
    Prüfung ist die Prüf-Wiederherstellung und läuft dort, wo der Schlüssel
    liegt.
    """
    if not path.is_file():
        return False
    return _sha256(path) == expected.strip().lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "IDENTIFIER_PATTERN",
    "OFFBOARDING_MARKER",
    "RECIPIENT_PATTERN",
    "RETENTION_HINT",
    "BackupArtifact",
    "BackupError",
    "backup_path",
    "check_recipient",
    "create_backup",
    "verify_checksum",
    "write_offboarding_marker",
    "write_retention_hint",
]
