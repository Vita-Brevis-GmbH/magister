"""Protokollierung des Agenten (ADR-0014).

Zwei Betriebsarten, ein Format:

* **Von Hand aufgerufen** (``enroll``, ``check``) — nach ``stderr``. Wer den
  Befehl tippt, will die Antwort sehen.
* **Als Dienst** — in eine Datei. Ein Windows-Dienst hat kein Terminal;
  ``stderr`` geht dort ins Nichts, und unter systemd landet es im Journal, was
  auf einem Kundenserver niemand liest, wenn er nicht weiss, dass er es lesen
  müsste. Eine Datei neben dem Zustand ist der Ort, den man in einem Runbook
  nennen kann.

Die Datei wird **rotiert**. Ohne Rotation wächst sie mit jedem Long-Poll, und
in einem Jahr hat der Kunde eine Protokolldatei, die grösser ist als sein
Zustandsverzeichnis — auf einem Server, den niemand ansieht, bis er voll ist.

Was **nicht** hineingeschrieben wird, steht in CLAUDE.md und gilt hier
unverändert: keine Passwörter, keine Token, keine Bind-Strings. Der Agent
protokolliert Auftragskennungen und Methodennamen; DNs stehen nur im lokalen
Protokoll beim Kunden und gehen nie an die Plattform.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

#: Grösse, ab der rotiert wird, und wie viele Stände bleiben. 5 mal 2 MiB ist
#: gross genug für ein paar Wochen Betrieb und klein genug, um in einen
#: Fehlerbericht zu passen.
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"

#: Name der Protokolldatei im Zustandsverzeichnis.
LOG_FILENAME = "agent.log"


def log_path(state_dir: Path) -> Path:
    return state_dir / LOG_FILENAME


def configure_stderr(verbose: bool = False) -> None:
    """Für den Aufruf von Hand."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=FORMAT,
        stream=sys.stderr,
    )


def configure_file(state_dir: Path, *, verbose: bool = False) -> Path:
    """Für den Dienstbetrieb. Gibt den Pfad der Protokolldatei zurück.

    Scheitert das Öffnen der Datei, wird **nicht** abgebrochen: ein Agent, der
    wegen seines Protokolls nicht läuft, ist schlechter als einer, der ohne
    Protokoll läuft. Die Meldung geht dann nach ``stderr`` — im Dienstbetrieb
    ins Nichts, aber beim Aufruf von Hand sichtbar, und genau dort sucht
    jemand danach.
    """
    target = log_path(state_dir)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            target,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as exc:
        configure_stderr(verbose)
        logging.getLogger(__name__).error(
            "Protokolldatei %s nicht schreibbar (%s). Der Agent läuft weiter, "
            "protokolliert aber nur nach stderr.",
            target,
            exc,
        )
        return target
    handler.setFormatter(logging.Formatter(FORMAT))
    # Vorhandene Handler ersetzen und nicht ergänzen: sonst schreibt ein
    # zweiter Aufruf jede Zeile doppelt.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    return target


__all__ = [
    "BACKUP_COUNT",
    "FORMAT",
    "LOG_FILENAME",
    "MAX_BYTES",
    "configure_file",
    "configure_stderr",
    "log_path",
]
