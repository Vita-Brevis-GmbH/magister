"""AD über den Connector-Agenten im Kundennetz (ADR-0014).

Der dritte Rücken hinter derselben ``AdClient``-Schnittstelle. Kein Aufrufer im
Fachcode ändert sich: dieselben Methoden, dieselben Ausnahmen. Nur der Weg ist
anders — statt LDAP zu sprechen, stellt dieser Rücken einen Auftrag in die
Warteschlange der Konsole und wartet auf das Ergebnis, das der Agent von innen
abliefert.

**Warum die Warteschlange in der Konsole liegt und nicht im Kundenschema:** der
Connector-Endpunkt ist öffentlich (TCP 46200) und bedient alle Kunden. Läge die
Warteschlange im Kundenschema, bräuchte er eine Datenbankrolle mit Zugriff auf
jedes Kundenschema — genau die Rolle, die es nach ADR-0013 D1 nicht geben darf.
Die Konsolen-Datenbank ist deshalb der richtige Ort.

**Was das kostet, offen gesagt:** AD-Operationen eines gehosteten Kunden hängen
damit an der Erreichbarkeit der Konsole. ADR-0013 D4 sagt „ein Ausfall der
Konsole lässt jeden Kunden weiterlaufen" — das gilt weiter für die Anwendung
selbst (Anmeldung, Klassen, Auswertungen, alles aus dem Kundenschema), aber
**nicht** für Passwort-Reset und AD-Sync. Die laufen über diesen Weg und
brauchen die Konsole. Bei einer Einzelinstallation fällt das zusammen: dort ist
die Konsole derselbe Aufbau mit n=1.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from magister_api.ad.errors import AdUnavailableError
from magister_api.ad.remote_base import RemoteAdClient
from magister_api.config import Settings

logger = logging.getLogger(__name__)

#: Wie lange auf ein Ergebnis gewartet wird. Muss unter der Lebensdauer eines
#: Auftrags in der Konsole liegen (dort 90 s), sonst wartet der Anwender auf
#: etwas, das schon verfallen ist.
DEFAULT_TIMEOUT_S = 60.0

#: Abstand zwischen zwei Abfragen des Ergebnisses. Kurz genug, dass ein
#: Passwort-Reset nicht künstlich langsam wirkt; lang genug, dass eine
#: Warteschlange von zwanzig Kunden die Konsole nicht mit Abfragen flutet.
POLL_INTERVAL_S = 0.5

#: Zeitüberschreitung einer einzelnen HTTP-Anfrage an die Konsole.
HTTP_TIMEOUT_S = 10.0


class AdConnectorClient(RemoteAdClient):
    """Stellt Aufträge in die Konsole und wartet auf den Agenten."""

    def __init__(
        self,
        settings: Settings,
        *,
        console_url: str,
        token: str,
        tenant_id: str,
        management_marker: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(settings)
        self._base = console_url.rstrip("/")
        self._tenant_id = tenant_id
        self._timeout_s = timeout_s
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if management_marker:
            # Die Konsole verwirft alles ohne diesen Marker (ADR-0015 D1). Die
            # Datenebene spricht sie über das Management-Netz an.
            headers["X-Magister-Management"] = management_marker
        self._http = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=headers, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- Transport --------------------------------------------------------
    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        job_id = await self._enqueue(method, payload)
        return await self._await_result(job_id, method)

    async def _enqueue(self, method: str, payload: dict[str, Any]) -> str:
        url = f"{self._base}/api/tenants/{self._tenant_id}/jobs"
        try:
            resp = await self._http.post(url, json={"method": method, "payload": payload})
        except httpx.HTTPError as exc:
            # Konsole nicht erreichbar ist aus Sicht des Aufrufers ein
            # AD-Ausfall — dieselbe Klasse, die der direkte Client wirft.
            raise AdUnavailableError("connector_console_unreachable") from exc
        if resp.status_code == 400:
            # Methode nicht in der Allowlist. Ein Programmierfehler, kein
            # Betriebszustand: der Aufrufer hat eine Methode benutzt, die über
            # den Connector nicht angeboten wird.
            raise AdUnavailableError("connector_method_not_allowed")
        if resp.status_code != 201:
            logger.warning(
                "Konsole nahm den Auftrag %s nicht an: HTTP %s", method, resp.status_code
            )
            raise AdUnavailableError("connector_enqueue_failed")
        job_id = str(resp.json().get("id", ""))
        if not job_id:
            raise AdUnavailableError("connector_enqueue_failed")
        return job_id

    async def _await_result(self, job_id: str, method: str) -> Any:
        url = f"{self._base}/api/tenants/{self._tenant_id}/jobs/{job_id}"
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                resp = await self._http.get(url)
            except httpx.HTTPError as exc:
                raise AdUnavailableError("connector_console_unreachable") from exc
            if resp.status_code != 200:
                raise AdUnavailableError("connector_poll_failed")
            body = resp.json()
            state = str(body.get("state", ""))
            if state == "done":
                return body.get("result")
            if state == "failed":
                # Der Agent hat es versucht und ist gescheitert. Der Grund
                # kommt aus dem Kundennetz und ist damit fremder Text — er
                # geht in das Log, aber nicht als Fehlermeldung an den Browser.
                logger.warning(
                    "Connector-Auftrag %s (%s) im Kundennetz gescheitert: %s",
                    job_id,
                    method,
                    body.get("error"),
                )
                raise AdUnavailableError("connector_job_failed")
            if state == "expired":
                # Der Agent war weg. Genau dafür verfallen Aufträge: ein spät
                # ausgeführter Passwort-Reset setzte das alte Passwort, nachdem
                # der Anwender längst ein neues gewählt hat.
                logger.warning("Connector-Auftrag %s (%s) ist verfallen", job_id, method)
                raise AdUnavailableError("connector_agent_unavailable")
            if time.monotonic() >= deadline:
                logger.warning(
                    "Auf Connector-Auftrag %s (%s) wurde %.0fs gewartet, Zustand %s",
                    job_id,
                    method,
                    self._timeout_s,
                    state or "unbekannt",
                )
                raise AdUnavailableError("connector_timeout")
            await asyncio.sleep(POLL_INTERVAL_S)


__all__ = ["AdConnectorClient"]
