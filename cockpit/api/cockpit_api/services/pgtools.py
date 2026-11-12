"""Externe Werkzeuge aufrufen: ``pg_dump``, ``pg_restore``, ``age``.

Alles hier ist **blockierend** und läuft über ``anyio.to_thread.run_sync``,
nicht über ``asyncio.create_subprocess_exec``. Zwei Gründe, beide beim Bauen
gelernt:

1. Die asyncio-Kindprozesse hängen am Event-Loop. Wird der Loop geschlossen,
   bevor der Transport aufgeräumt ist, kommt aus ``__del__`` eine
   ``RuntimeError: Event loop is closed`` — im Test als
   ``PytestUnraisableExceptionWarning``, im Betrieb als Rauschen im Protokoll
   mit einem Stacktrace, der auf nichts zeigt. Ein Thread mit ``Popen`` hat
   diesen Zustand nicht.
2. ``asyncio`` kann den ``StreamReader`` eines Prozesses **nicht** als stdin
   eines anderen nehmen (``'StreamReader' object has no attribute 'fileno'``).
   Eine Kette braucht so oder so echte Dateideskriptoren — dann besser gleich
   mit dem Werkzeug, das dafür gemacht ist.

Der **stderr jedes Prozesses geht in eine temporäre Datei**, nicht in eine
Pipe. Eine Kette aus zwei Prozessen, bei der der Elternprozess auf den zweiten
wartet, verklemmt, sobald der erste mehr als einen Pipe-Puffer (64 KiB) auf
stderr schreibt. Mit einer Datei ist dieser Zustand nicht erreichbar.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import anyio.to_thread
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """Ein externes Werkzeug ist gescheitert. Trägt die letzte Meldung."""


@dataclass(frozen=True, slots=True)
class Stage:
    """Ein Prozess in einer Kette."""

    argv: Sequence[str]
    env: dict[str, str] | None = None
    #: Datei, in die stdout geschrieben wird (nur für die letzte Stufe).
    stdout_path: Path | None = None
    #: Datei, aus der stdin gelesen wird (nur für die erste Stufe).
    stdin_path: Path | None = None
    label: str = field(default="")

    @property
    def name(self) -> str:
        return self.label or (self.argv[0] if self.argv else "?")


def libpq_env(dsn: str) -> dict[str, str]:
    """libpq-Umgebung aus einem DSN. Passwort über ``PGPASSWORD``, nie über argv.

    argv ist auf einem Mehrbenutzersystem für jeden in ``ps`` sichtbar; die
    Umgebung eines fremden Prozesses ist es nicht.
    """
    url = make_url(dsn)
    env = dict(os.environ)
    host = url.query.get("host")
    if isinstance(host, str) and host:
        env["PGHOST"] = host
    elif url.host:
        env["PGHOST"] = url.host
    port = url.query.get("port")
    if isinstance(port, str) and port:
        env["PGPORT"] = port
    elif url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    if url.database:
        env["PGDATABASE"] = url.database
    return env


def _stderr_tail(handle: IO[bytes]) -> str:
    handle.seek(0)
    lines = handle.read().decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else ""


def _run_chain_blocking(first: Stage, second: Stage) -> None:
    """``first | second`` — ohne Shell, ohne Zwischendatei.

    Eine Zwischendatei wäre bei uns immer die *unverschlüsselte* Variante des
    Dumps auf der Platte. Genau die soll es nicht geben, auch nicht für
    Sekunden und auch nicht, wenn der Prozess mittendrin abbricht.
    """
    with tempfile.TemporaryFile() as first_err, tempfile.TemporaryFile() as second_err:
        stdin_handle = first.stdin_path.open("rb") if first.stdin_path else None
        stdout_handle = second.stdout_path.open("wb") if second.stdout_path else None
        try:
            rc_first, rc_second = _spawn_pair(
                first,
                second,
                stdin_handle=stdin_handle,
                stdout_handle=stdout_handle,
                first_err=first_err,
                second_err=second_err,
            )
        finally:
            if stdin_handle is not None:
                stdin_handle.close()
            if stdout_handle is not None:
                stdout_handle.close()

        if rc_first != 0 or rc_second != 0:
            failed = first if rc_first != 0 else second
            detail = (
                _stderr_tail(first_err if rc_first != 0 else second_err)
                or f"Rückgabewert {rc_first if rc_first != 0 else rc_second}"
            )
            raise ToolError(f"{failed.name}: {detail}")


def _spawn_pair(
    first: Stage,
    second: Stage,
    *,
    stdin_handle: IO[bytes] | None,
    stdout_handle: IO[bytes] | None,
    first_err: IO[bytes],
    second_err: IO[bytes],
) -> tuple[int, int]:
    """Beide Prozesse starten, verbinden, abwarten. Gibt die Rückgabewerte."""
    read_fd, write_fd = os.pipe()
    p_first: subprocess.Popen[bytes] | None = None
    try:
        p_first = subprocess.Popen(
            list(first.argv),
            env=first.env,
            stdin=stdin_handle or subprocess.DEVNULL,
            stdout=write_fd,
            stderr=first_err,
        )
        p_second = subprocess.Popen(
            list(second.argv),
            env=second.env,
            stdin=read_fd,
            stdout=stdout_handle or subprocess.DEVNULL,
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
        # BEIDE Enden im Elternprozess schliessen. Bleibt das Schreibende
        # offen, bekommt die zweite Stufe kein EOF und die Kette hängt für
        # immer; bleibt das Leseende offen, merkt die erste Stufe nicht, wenn
        # die zweite weg ist.
        os.close(write_fd)
        os.close(read_fd)

    rc_second = p_second.wait()
    rc_first = p_first.wait()
    return rc_first, rc_second


async def run_chain(first: Stage, second: Stage) -> None:
    """``first | second`` in einem Thread, damit der Loop frei bleibt.

    Ein ``pg_dump`` über ein grosses Kundenschema läuft Minuten. Im
    Request-Pfad würde das den ganzen Prozess anhalten — deshalb Thread, wie
    bei den LDAP-Aufrufen (CLAUDE.md: nie synchron im async Pfad).
    """
    await anyio.to_thread.run_sync(_run_chain_blocking, first, second)


def _run_blocking(stage: Stage) -> bytes:
    with tempfile.TemporaryFile() as err:
        completed = subprocess.run(
            list(stage.argv),
            env=stage.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=err,
            check=False,
        )
        if completed.returncode != 0:
            detail = _stderr_tail(err) or f"Rückgabewert {completed.returncode}"
            raise ToolError(f"{stage.name}: {detail}")
        return completed.stdout or b""


async def run_tool(stage: Stage) -> bytes:
    """Ein einzelnes Werkzeug aufrufen und stdout zurückgeben."""
    return await anyio.to_thread.run_sync(_run_blocking, stage)


__all__ = ["Stage", "ToolError", "libpq_env", "run_chain", "run_tool"]
