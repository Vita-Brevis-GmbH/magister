"""Konfiguration und Zustand des Agenten (ADR-0014).

Getrennt gehalten: die **Konfiguration** kommt vom Kunden und ändert sich
selten (Endpunkt, OU-Allowlist, AD-Zugang). Der **Zustand** entsteht bei der
Anmeldung (Zertifikat, Schlüssel, API-Key) und gehört dem Agenten.

Der private Schlüssel und die Geheimnisse liegen mit ``0600`` in einem
Verzeichnis mit ``0700``. Der Agent prüft das beim Start und **weigert sich**,
mit zu weiten Rechten zu laufen — eine Warnung würde überlesen, und die Datei
liegt auf einem Server, auf dem mehr als eine Person ein Konto hat.

Unter **Windows** ist derselbe Satz wahr, aber die Prüfung eine andere: dort
schützt die ACL und nicht ein POSIX-Modus. ``os.stat()`` liefert unter Windows
erfundene Modus-Bits (Verzeichnisse melden ``0o777``), die POSIX-Prüfung würde
also immer fehlschlagen und der Dienst nie starten. Geprüft wird deshalb die
DACL — siehe :mod:`connector_agent.winsec`. Sie stumm zu überspringen wäre die
schlechteste der drei Möglichkeiten: der Agent liefe, und die Zusage über den
privaten Schlüssel wäre unbelegt.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from connector_agent.guardrails import DEFAULT_PROTECTED_GROUPS, Guardrails

logger = logging.getLogger(__name__)

#: Rechte, die das Zustandsverzeichnis haben muss (nur POSIX).
DIR_MODE = 0o700

#: Rechte, die eine Geheimnisdatei haben muss (nur POSIX).
FILE_MODE = 0o600

#: Läuft der Agent unter Windows? Einmal ausgewertet, damit die Verzweigungen
#: unten lesbar bleiben.
IS_WINDOWS = os.name == "nt"

#: Vorgabe für das Zustandsverzeichnis, je Betriebssystem.
#:
#: Unter Windows ``%ProgramData%``: dort gehören Daten hin, die zur Maschine
#: und nicht zu einem Benutzer gehören, und das Installationsprogramm kann die
#: ACL darauf setzen. ``%ProgramFiles%`` wäre falsch — dort schreibt ein
#: Dienst nichts hinein, und ein Update würde es überschreiben.
DEFAULT_STATE_DIR = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Magister Connector"
    if IS_WINDOWS
    else Path("/var/lib/magister-connector")
)

#: Vorgabe für die Konfigurationsdatei.
DEFAULT_CONFIG_PATH = (
    DEFAULT_STATE_DIR / "config.json" if IS_WINDOWS else Path("/etc/magister-connector/config.json")
)


class ConfigError(RuntimeError):
    """Die Konfiguration ist unbrauchbar. Immer fatal, nie eine Warnung."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Was der Kunde konfiguriert."""

    #: Basis-URL des Connector-Kanals, z. B. ``https://connect.magister.ch:46200``.
    endpoint: str
    #: Verzeichnis für Zertifikat, Schlüssel und Geheimnisse.
    state_dir: Path
    #: CA-Bundle der Plattform, gegen das der Agent den Server prüft. Das ist
    #: die Gegenrichtung zum Client-Zertifikat: ohne diese Prüfung könnte ein
    #: Angreifer im Netz die Plattform spielen und Aufträge erteilen.
    ca_bundle: Path
    #: Lokale OU-Allowlist. Leer heisst: keine Verzeichnisaufträge (siehe
    #: guardrails._check_dns) — nicht "alles erlaubt".
    allowed_ous: frozenset[str] = frozenset()
    #: Geschützte Gruppen. Die eingebaute Liste ist eine **Untergrenze** —
    #: Einträge aus der Konfiguration kommen dazu und ersetzen sie nicht.
    protected_groups: frozenset[str] = DEFAULT_PROTECTED_GROUPS
    #: Ausgehender HTTP-Proxy, falls das Kundennetz einen verlangt. Bewusst
    #: **explizit** und nicht aus ``HTTPS_PROXY`` der Umgebung: der Kanal
    #: trägt ein Client-Zertifikat, und ob das ankommt, darf nicht davon
    #: abhängen, was irgendwann jemand in ein Profil geschrieben hat. Ein
    #: Proxy, der TLS aufbricht, macht die Client-Authentisierung unmöglich —
    #: dann muss der Kunde ihn für diesen Host umgehen.
    proxy: str | None = None
    #: Sekunden, die ein Long-Poll offen bleibt.
    poll_seconds: int = 25
    #: Wartezeit nach einem Fehler, bevor erneut angeklopft wird.
    backoff_seconds: float = 5.0

    @property
    def guardrails(self) -> Guardrails:
        return Guardrails(allowed_ous=self.allowed_ous, protected_groups=self.protected_groups)

    @property
    def cert_path(self) -> Path:
        return self.state_dir / "agent.pem"

    @property
    def key_path(self) -> Path:
        return self.state_dir / "agent-key.pem"

    @property
    def secrets_path(self) -> Path:
        return self.state_dir / "secrets.json"

    @classmethod
    def from_file(cls, path: Path) -> AgentConfig:
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Konfigurationsdatei {path} fehlt.") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Konfigurationsdatei {path} ist kein gültiges JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"Konfigurationsdatei {path} muss ein JSON-Objekt sein.")
        return cls.from_mapping(cast(dict[str, Any], raw))

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> AgentConfig:
        endpoint = str(raw.get("endpoint") or "").strip().rstrip("/")
        if not endpoint.startswith("https://"):
            # Kein Klartext, auch nicht im eigenen Netz: über diese Leitung
            # gehen Passwörter.
            raise ConfigError(
                "endpoint muss eine https-URL sein. Über diesen Kanal laufen "
                "Passwörter; ein Klartext-Transport ist keine Option."
            )
        state_dir = Path(str(raw.get("state_dir") or DEFAULT_STATE_DIR))
        ca_bundle = Path(str(raw.get("ca_bundle") or state_dir / "platform-ca.pem"))
        ous = frozenset(
            text for text in (str(o).strip() for o in _string_list(raw.get("allowed_ous"))) if text
        )
        # VEREINIGUNG, nicht Ersetzung: die eingebaute Liste ist eine
        # Untergrenze. Wer eine eigene geschützte Gruppe eintragen will, soll
        # dabei nicht den Schutz für „Domänen-Admins" verlieren — und genau
        # das täte er, wenn die Konfiguration die Vorgabe ersetzte. Der Fehler
        # wäre still: alles läuft, und die Plattform darf plötzlich Konten in
        # die Domänen-Admins aufnehmen.
        configured_groups = frozenset(
            text
            for text in (str(g).strip().lower() for g in _string_list(raw.get("protected_groups")))
            if text
        )
        groups = DEFAULT_PROTECTED_GROUPS | configured_groups
        proxy_raw = raw.get("proxy")
        proxy = str(proxy_raw).strip() if isinstance(proxy_raw, str) and proxy_raw.strip() else None
        return cls(
            endpoint=endpoint,
            state_dir=state_dir,
            ca_bundle=ca_bundle,
            allowed_ous=ous,
            protected_groups=groups,
            proxy=proxy,
            poll_seconds=int(raw.get("poll_seconds") or 25),
            backoff_seconds=float(raw.get("backoff_seconds") or 5.0),
        )


def _string_list(value: object) -> list[Any]:
    """Liste aus dem JSON holen, ohne über ihren Inhalt zu raten."""
    if isinstance(value, list):
        return cast(list[Any], value)
    return []


@dataclass(frozen=True, slots=True)
class AgentSecrets:
    agent_id: str
    api_key: str
    result_hmac_key: str
    spki_sha256: str


def ensure_state_dir(state_dir: Path) -> None:
    """Zustandsverzeichnis anlegen und abdichten.

    Zwei Betriebssysteme, zwei Mechanismen: unter Linux ``0700``, unter
    Windows eine ACL, die nur SYSTEM und den Administratoren etwas gibt. Beides
    macht der **Agent** und nicht das Installationsprogramm — dann gilt es für
    jede Installationsart gleich, auch für die, die jemand „schnell zum Testen"
    gemacht hat.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        from connector_agent.winsec import WindowsPermissionError, harden_directory

        try:
            harden_directory(state_dir)
        except WindowsPermissionError as exc:
            raise ConfigError(str(exc)) from exc
        return
    state_dir.chmod(DIR_MODE)


def write_secret_file(path: Path, content: str) -> None:
    """Datei mit ``0600`` schreiben, und zwar von Anfang an.

    ``open`` und danach ``chmod`` hinterlässt ein Fenster, in dem die Datei mit
    der Standardmaske lesbar ist. Auf einem Server mit mehreren Konten ist das
    genau das Fenster, das man nicht will — deshalb ``os.open`` mit dem Modus.

    Unter Windows tut der Modus fast nichts (er setzt nur das
    Read-Only-Attribut). Der Schutz kommt dort von der ACL des
    Zustandsverzeichnisses, die die Datei erbt — gesetzt vom
    Installationsprogramm und bei jedem Start von ``assert_permissions``
    nachgeprüft. Das ``0600`` bleibt trotzdem stehen: es kostet nichts und ist
    unter Linux die ganze Miete.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        # fdopen übernimmt den Deskriptor; ein zweites close wäre ein Fehler.
        pass
    path.chmod(FILE_MODE)


def assert_permissions(config: AgentConfig) -> None:
    """Rechte prüfen und bei zu weiten abbrechen.

    Verweigerung statt Warnung: eine Warnung im Dienst-Log liest niemand, und
    ein weltlesbarer privater Schlüssel ist kein Zustand, in dem man
    weiterarbeitet.

    Zwei Betriebssysteme, zwei Mechanismen, eine Zusage. Unter Windows prüft
    :func:`connector_agent.winsec.assert_windows_permissions` die DACL; der
    POSIX-Modus ist dort ein Phantasiewert und taugt für keine Aussage.
    """
    if not config.state_dir.is_dir():
        raise ConfigError(f"Zustandsverzeichnis {config.state_dir} fehlt.")
    if IS_WINDOWS:
        _assert_windows(config)
        return
    dir_mode = stat.S_IMODE(config.state_dir.stat().st_mode)
    if dir_mode & 0o077:
        raise ConfigError(
            f"Zustandsverzeichnis {config.state_dir} hat Rechte {dir_mode:04o}. "
            f"Erwartet {DIR_MODE:04o} — dort liegt der private Schlüssel des Agenten."
        )
    for path in (config.key_path, config.secrets_path):
        if not path.exists():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o177:
            raise ConfigError(
                f"{path} hat Rechte {mode:04o}, erwartet {FILE_MODE:04o}. "
                "Der Agent läuft nicht mit einem lesbaren Geheimnis."
            )


def _assert_windows(config: AgentConfig) -> None:
    """ACL des Zustandsverzeichnisses prüfen.

    Nur das Verzeichnis, nicht jede Datei darin: die Dateien erben ihre Rechte
    von ihm (das Installationsprogramm setzt ``(OI)(CI)``), und ``winsec``
    verlangt zusätzlich, dass das Verzeichnis selbst **nicht** erbt. Damit ist
    die ACL des Verzeichnisses die vollständige Aussage über den Inhalt.
    """
    from connector_agent.winsec import (
        WindowsPermissionError,
        assert_windows_permissions,
    )

    try:
        assert_windows_permissions(config.state_dir, what="Zustandsverzeichnis")
    except WindowsPermissionError as exc:
        raise ConfigError(str(exc)) from exc


def load_secrets(config: AgentConfig) -> AgentSecrets | None:
    if not config.secrets_path.exists():
        return None
    raw = json.loads(config.secrets_path.read_text(encoding="utf-8"))
    return AgentSecrets(
        agent_id=str(raw["agent_id"]),
        api_key=str(raw["api_key"]),
        result_hmac_key=str(raw["result_hmac_key"]),
        spki_sha256=str(raw["spki_sha256"]),
    )


def save_secrets(config: AgentConfig, secrets: AgentSecrets) -> None:
    write_secret_file(
        config.secrets_path,
        json.dumps(
            {
                "agent_id": secrets.agent_id,
                "api_key": secrets.api_key,
                "result_hmac_key": secrets.result_hmac_key,
                "spki_sha256": secrets.spki_sha256,
            },
            indent=2,
        ),
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_STATE_DIR",
    "IS_WINDOWS",
    "AgentConfig",
    "AgentSecrets",
    "ConfigError",
    "assert_permissions",
    "ensure_state_dir",
    "load_secrets",
    "save_secrets",
    "write_secret_file",
]
