"""Der Agent als Windows-Dienst (ADR-0014).

    magister-connector-service.exe install|start|stop|remove

Warum ein eigenes Modul und nicht ``sc.exe create … binPath="agent.exe run"``:
Windows erwartet von einem Dienstprozess, dass er innerhalb von rund 30
Sekunden ``StartServiceCtrlDispatcher`` aufruft und sich beim Dienst-Manager
meldet. Ein gewöhnliches Konsolenprogramm tut das nicht und scheitert mit
„Fehler 1053: Der Dienst hat nicht auf die Startanforderung reagiert" — auch
wenn es einwandfrei läuft. Es braucht also einen echten Dienst-Einsprungpunkt.

Über ``pywin32`` und nicht über einen fremden Dienst-Wrapper (NSSM, WinSW):
das wären ein weiteres Programm im Paket und eine weitere Herkunft, die man
dem Kunden erklären und mit ausliefern muss. ``pywin32`` ist eine Bibliothek,
die PyInstaller mit einpackt.

**Die Sprungstelle zwischen zwei Fäden** ist der einzige heikle Punkt hier:
``SvcStop`` ruft Windows in einem anderen Thread auf als dem, in dem die
Ereignisschleife läuft. Ein ``stop.set()`` von dort wäre ein Zugriff auf ein
``asyncio``-Objekt aus einem fremden Thread — der Klassiker, der einmal in
zehn Fällen hängt. Deshalb ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# pywin32 gibt es nur unter Windows. Der Import steht hier oben, weil dieses
# Modul ausschliesslich dort geladen wird — unter Linux importiert es niemand.
import servicemanager  # type: ignore[import-not-found]
import win32event  # type: ignore[import-not-found]
import win32service  # type: ignore[import-not-found]
import win32serviceutil  # type: ignore[import-not-found]

from connector_agent.config import (
    DEFAULT_CONFIG_PATH,
    AgentConfig,
    ConfigError,
    assert_permissions,
    load_secrets,
)
from connector_agent.logsetup import configure_file

logger = logging.getLogger("connector_agent.service")

#: Umgebungsvariable, mit der ein Betreiber die Konfiguration verschieben kann.
#: Der Dienst liest sie beim Start; gesetzt wird sie in der Dienst-Umgebung
#: (``sc.exe`` schreibt sie nicht, das tut die Registry oder das
#: Installationsprogramm).
CONFIG_ENV = "MAGISTER_CONNECTOR_CONFIG"


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG_PATH)


class MagisterConnectorService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
    """Der Dienst. Ein Auftrag zur Zeit, kein Zwischenspeicher, kein Neuversuch."""

    _svc_name_ = "MagisterConnector"
    _svc_display_name_ = "Magister Connector-Agent"
    _svc_description_ = (
        "Holt Verzeichnisaufträge von der Magister-Plattform ab und führt sie "
        "gegen das lokale Active Directory aus. Baut ausschliesslich "
        "ausgehende Verbindungen auf; nimmt keine an."
    )

    def __init__(self, args: list[str]) -> None:
        super().__init__(args)  # type: ignore[no-untyped-call]
        # Ein Windows-Ereignis für den Fall, dass die Schleife noch nicht
        # steht, wenn der Stopp kommt.
        self._wait = win32event.CreateEvent(None, 0, 0, None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    # -- Windows ruft auf ------------------------------------------------
    def SvcStop(self) -> None:  # noqa: N802 — von pywin32 vorgegeben
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)  # type: ignore[no-untyped-call]
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None:
            # Aus einem FREMDEN Thread in die Schleife hinein. Ein direktes
            # stop.set() wäre genau der Zugriff, der gelegentlich hängt.
            loop.call_soon_threadsafe(stop.set)
        win32event.SetEvent(self._wait)

    def SvcDoRun(self) -> None:  # noqa: N802 — von pywin32 vorgegeben
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            asyncio.run(self._serve())
        except Exception:
            # Ins Ereignisprotokoll, damit ein Absturz sichtbar ist, auch wenn
            # niemand die Protokolldatei kennt. Der Stacktrace geht in die
            # Datei; hier steht nur, dass es passiert ist und wo man nachsieht.
            logger.exception("Der Dienst ist abgebrochen.")
            servicemanager.LogErrorMsg(
                f"Magister Connector-Agent abgebrochen. Einzelheiten in {configured_log_path()}."
            )
            raise

    # -- die eigentliche Arbeit ------------------------------------------
    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()

        path = config_path()
        try:
            config = AgentConfig.from_file(path)
        except ConfigError as exc:
            self._fail(f"Konfiguration {path}: {exc}")
            return
        configure_file(config.state_dir)

        try:
            assert_permissions(config)
        except ConfigError as exc:
            # Der ausführlichste Fall im Betrieb: unter Windows steht hier die
            # icacls-Zeile, mit der man es richtet.
            self._fail(str(exc))
            return

        secrets = load_secrets(config)
        if secrets is None:
            self._fail(
                "Der Agent ist nicht angemeldet. Zuerst 'magister-connector "
                "enroll' mit dem Einmal-Token aus der Konsole ausführen, dann "
                "den Dienst starten."
            )
            return

        from connector_agent.cli import VERSION, build_ad_client
        from connector_agent.runner import AdExecutor, Runner

        ad = build_ad_client()
        if ad is None:
            self._fail(
                "Der AD-Zugang ist unvollständig. Die MAGISTER_AD_*-Werte "
                "gehören in die Umgebung des Dienstes."
            )
            return

        runner = Runner(
            config=config,
            secrets=secrets,
            executor=AdExecutor(ad),
            guardrails=config.guardrails,
            agent_version=VERSION,
        )
        logger.info(
            "Dienst läuft. Endpunkt %s, %d erlaubte OU(s), %d geschützte Gruppe(n).",
            config.endpoint,
            len(config.allowed_ous),
            len(config.protected_groups),
        )
        if not config.allowed_ous:
            logger.warning(
                "Es ist keine OU-Allowlist konfiguriert. Verzeichnisaufträge "
                "werden abgelehnt, bis eine steht — das ist Absicht."
            )
        await runner.serve_forever(self._stop)
        logger.info("Dienst beendet.")

    def _fail(self, message: str) -> None:
        """Sauber scheitern: Meldung ins Ereignisprotokoll, Dienst stoppt.

        Kein endloser Neustart-Kreis: was hier scheitert, behebt ein Mensch
        (fehlende Anmeldung, falsche Rechte, unvollständige Konfiguration).
        Ein Dienst, der sich alle 30 Sekunden neu startet, verdeckt das nur
        und füllt das Ereignisprotokoll.
        """
        logger.error("%s", message)
        servicemanager.LogErrorMsg(f"Magister Connector-Agent startet nicht: {message}")


def configured_log_path() -> Path:
    """Wo das Protokoll liegt — für die Meldung im Ereignisprotokoll."""
    from connector_agent.logsetup import log_path

    try:
        return log_path(AgentConfig.from_file(config_path()).state_dir)
    except ConfigError:
        return Path(DEFAULT_CONFIG_PATH).parent / "agent.log"


def main() -> None:
    """Einsprungpunkt der Dienst-Exe.

    Ohne Argumente startet Windows sie als Dienst; mit ``install``,
    ``start``, ``stop``, ``remove`` verwaltet ``win32serviceutil`` sie von der
    Kommandozeile. Das Installationsprogramm benutzt ``sc.exe`` und nicht
    diesen Weg — aber für die Fehlersuche beim Kunden ist er da.
    """
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MagisterConnectorService)
        servicemanager.StartServiceCtrlDispatcher()  # type: ignore[no-untyped-call]
        return
    win32serviceutil.HandleCommandLine(  # type: ignore[no-untyped-call]
        MagisterConnectorService
    )


if __name__ == "__main__":
    main()
