"""Zwei Prozesse als Kette, ohne Shell und ohne Zwischendatei.

Gebraucht an zwei Stellen, und beide Male aus demselben Grund: was zwischen
den Prozessen fliesst, ist ein **unverschlüsselter Dump**. Eine Zwischendatei
wäre genau das Ding, das die Verschlüsselung verhindern soll — und sie liegt
dort auch dann noch, wenn der Prozess mittendrin abbricht.

    pg_dump  | age -r …   (sichern, cli/tenants.py)
    age -d … | pg_restore (prüfen,  cli/backup.py)

Drei Dinge, die hier einmal richtig stehen, weil sie zweimal falsch sein
könnten:

1. **Beide Enden der Pipe schliesst der Elternprozess.** Bleibt das
   Schreibende offen, bekommt die zweite Stufe kein EOF und die Kette hängt
   für immer; bleibt das Leseende offen, merkt die erste Stufe nicht, wenn die
   zweite weg ist.
2. **`stderr` geht in temporäre Dateien, nicht in Pipes.** Eine Kette, bei der
   der Elternprozess auf den zweiten Prozess wartet, verklemmt, sobald der
   erste mehr als einen Pipe-Puffer (64 KiB) auf `stderr` schreibt.
3. **Absolute Pfade statt Namen.** Diese Werkzeuge laufen im Cron, und dort ist
   `PATH` ein anderer als in einer Anmeldesitzung. Ein „age: command not
   found" um 03:15 sieht aus wie ein kaputtes Backup und ist eine fehlende
   Zeile in der crontab.

Das Gegenstück in der Konsole ist ``cockpit_api/services/pgtools.py``. Bewusst
zwei Fassungen: die Datenebene darf nicht von der Konsole abhängen — eine
Gemeinde mit einem Server soll keinen Plattform-Betrieb mitinstallieren
(ADR-0016 D9). Die dortige Fassung ist zusätzlich async, weil sie im
Anfragepfad läuft; hier läuft alles in einem CLI und darf blockieren.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO


class PipeError(RuntimeError):
    """Eine Stufe der Kette ist gescheitert. Trägt deren letzte Meldung."""


@dataclass(frozen=True, slots=True)
class Stage:
    """Ein Prozess in der Kette."""

    argv: Sequence[str]
    env: dict[str, str] | None = None
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or (self.argv[0] if self.argv else "?")


def _tail(handle: IO[bytes]) -> str:
    handle.seek(0)
    lines = handle.read().decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else ""


def run_pipe(first: Stage, second: Stage, *, stdout_path: Path | None = None) -> None:
    """``first | second`` ausführen; ``stdout_path`` nimmt die Ausgabe der zweiten.

    Wirft :class:`PipeError`, sobald eine der beiden Stufen einen
    Rückgabewert ungleich 0 hat — mit der letzten Zeile ihres ``stderr``.
    Läuft alles gut, gibt es keine Ausgabe: dies ist die Mechanik, nicht der
    Vorgang.
    """
    with tempfile.TemporaryFile() as first_err, tempfile.TemporaryFile() as second_err:
        out_handle = stdout_path.open("wb") if stdout_path else None
        try:
            rc_first, rc_second = _spawn(
                first,
                second,
                out_handle=out_handle,
                first_err=first_err,
                second_err=second_err,
            )
        finally:
            if out_handle is not None:
                out_handle.close()

        if rc_first != 0 or rc_second != 0:
            failed = first if rc_first != 0 else second
            detail = (
                _tail(first_err if rc_first != 0 else second_err)
                or f"Rückgabewert {rc_first if rc_first != 0 else rc_second}"
            )
            raise PipeError(f"{failed.name}: {detail}")


def _spawn(
    first: Stage,
    second: Stage,
    *,
    out_handle: IO[bytes] | None,
    first_err: IO[bytes],
    second_err: IO[bytes],
) -> tuple[int, int]:
    read_fd, write_fd = os.pipe()
    p_first: subprocess.Popen[bytes] | None = None
    try:
        p_first = subprocess.Popen(  # noqa: S603 — feste Argumentliste, keine Shell
            list(first.argv),
            env=first.env,
            stdin=subprocess.DEVNULL,
            stdout=write_fd,
            stderr=first_err,
        )
        p_second = subprocess.Popen(  # noqa: S603 — feste Argumentliste, keine Shell
            list(second.argv),
            env=second.env,
            stdin=read_fd,
            stdout=out_handle or subprocess.DEVNULL,
            stderr=second_err,
        )
    except Exception:
        if p_first is not None:
            # Die zweite Stufe kam nicht zustande (Werkzeug fehlt, Rechte).
            # Ohne Leser würde die erste auf ein nie geleertes Rohr schreiben
            # und dort stehen bleiben.
            p_first.kill()
            p_first.wait()
        raise
    finally:
        os.close(write_fd)
        os.close(read_fd)

    rc_second = p_second.wait()
    rc_first = p_first.wait()
    return rc_first, rc_second


__all__ = ["PipeError", "Stage", "run_pipe"]
