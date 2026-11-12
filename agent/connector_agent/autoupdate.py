"""Selbstupdate im Wartungsfenster (ADR-0014 Nachtrag 2026-10).

Bis hier aktualisierte sich der Agent nie von selbst: er läuft als LocalSystem
auf dem Domänencontroller, und ein Update, das die Plattform auslösen kann,
gäbe einer übernommenen Plattform Code auf Tier 0. Daran ändert sich nichts —
geändert hat sich, **wer** über das Paket entscheidet:

* Installiert wird nur ein MSI mit gültiger **Ed25519-Signatur** eines
  Schlüssels aus :mod:`connector_agent.update_keys`. Der Schlüssel steht im
  Quelltext des Agenten, der private Teil liegt offline bei Vita Brevis. Die
  Plattform reicht MSI und Signatur nur durch; fälschen kann sie keines.
* Nur im **Wartungsfenster** (Ortszeit des DC, Vorgabe 02:00 bis 04:00) und nur,
  wenn das Cockpit es für diesen Kunden nicht abgeschaltet hat.
* **Eine Fassung, ein Versuch.** Scheitert sie (Rückfall auf die alte), wird
  sie nicht jede Nacht neu probiert; erst die nächste Fassung wieder.
* Was geschah, meldet der Agent der Plattform — das Cockpit zeigt es beim
  Connector des Kunden.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from connector_agent import remote as remote_cfg
from connector_agent import update as up
from connector_agent.config import AgentConfig, AgentSecrets
from connector_agent.update_keys import TRUSTED_KEYS

logger = logging.getLogger(__name__)

#: Wie oft nachgesehen wird. Das Fenster ist zwei Stunden breit; eine
#: Viertelstunde trifft es sicher, ohne die Plattform zu bemühen.
CHECK_SECONDS = 900.0

#: Merkzettel im Update-Verzeichnis: welches Ergebnis schon gemeldet ist.
REPORTED_FILE = "gemeldet.txt"

Launcher = Callable[[Path, Path | None], Path]


def _local_now() -> dt.datetime:
    return dt.datetime.now()


@dataclass
class AutoUpdater:
    config: AgentConfig
    secrets: AgentSecrets
    agent_version: str
    keys: dict[str, str] = field(default_factory=lambda: dict(TRUSTED_KEYS))
    launcher: Launcher = up.launch_install
    clock: Callable[[], dt.datetime] = _local_now
    transport: httpx.BaseTransport | None = None
    #: Monotone Zeit der letzten Runde (vom Runner geführt).
    last_tick: float | None = None
    _warned_no_keys: bool = field(default=False, init=False, repr=False)

    @property
    def folder(self) -> Path:
        return up.updates_dir(self.config)

    def due(self, moment: float) -> bool:
        if self.last_tick is not None and moment - self.last_tick < CHECK_SECONDS:
            return False
        self.last_tick = moment
        return True

    # -- Meldungen -----------------------------------------------------------
    def _report(self, outcome: str) -> None:
        logger.info("Update: %s", outcome)
        try:
            up.report(
                self.config,
                self.secrets,
                outcome,
                agent_version=self.agent_version,
                transport=self.transport,
            )
        except (httpx.HTTPError, up.UpdateError) as exc:
            logger.warning("Update-Ergebnis nicht gemeldet: %s", exc)

    def report_pending(self) -> None:
        """Das Ergebnis des letzten Einspielens melden, einmal.

        Geschrieben hat es das Installationsskript — der Agent, der es
        gestartet hat, lief da schon nicht mehr. Melden kann es erst der neu
        gestartete (oder nach einem Rückfall der alte).
        """
        result = self.folder / up.RESULT_FILE
        marker = self.folder / REPORTED_FILE
        if not result.is_file():
            return
        stamp = str(result.stat().st_mtime_ns)
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == stamp:
            return
        text = result.read_text(encoding="utf-8", errors="replace").strip()
        self._report(f"Eingespielt, läuft jetzt {self.agent_version}: {text}")
        marker.write_text(stamp, encoding="utf-8")

    # -- Runde ---------------------------------------------------------------
    def tick(self, remote: remote_cfg.RemoteConfig) -> str | None:
        """Eine Runde. Rückgabe: die Fassung, deren Installation gestartet wurde."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.report_pending()
        if not remote.auto_update:
            return None
        if not remote_cfg.in_window(remote.update_window, self.clock().time()):
            return None
        if not self.keys:
            if not self._warned_no_keys:
                logger.warning("Selbstupdate aus: im Agenten ist kein Signaturschlüssel eingebaut.")
                self._warned_no_keys = True
            return None
        info = up.check(
            self.config, self.secrets, agent_version=self.agent_version, transport=self.transport
        )
        if info is None or not up.is_newer(info.version, self.agent_version):
            return None
        # Ein Versuch je Paket (Fassung + Prüfsumme): ein neu signiertes Paket
        # derselben Fassung wird wieder versucht, ein gescheitertes nicht.
        marker = self.folder / f"versuch-{info.version}-{info.sha256[:12]}.txt"
        if marker.exists():
            return None
        marker.write_text(self.clock().isoformat(timespec="seconds"), encoding="utf-8")
        try:
            up.verify_signature(info, self.keys)
        except up.UpdateError as exc:
            self._report(f"{info.version} nicht installiert: {exc}")
            return None
        msi = up.download(
            self.config,
            self.secrets,
            info,
            agent_version=self.agent_version,
            transport=self.transport,
        )
        previous = up.msi_for_version(self.config, self.agent_version)
        self._report(
            f"{info.version}: Signatur gültig, Installation gestartet"
            + ("" if previous else " (kein Rückfall-Paket der laufenden Fassung)")
        )
        self.launcher(msi, previous)
        return info.version


__all__ = ["CHECK_SECONDS", "AutoUpdater"]
