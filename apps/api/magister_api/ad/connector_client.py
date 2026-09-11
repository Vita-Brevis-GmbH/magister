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
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

import httpx

from magister_api.ad.client import DEFAULT_USER_ATTRIBUTES, AdUserRecord
from magister_api.ad.errors import AdUnavailableError
from magister_api.ad.remote_base import RemoteAdClient
from magister_api.ad.rpc import ad_user_record_from_jsonable
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

#: Wartezeit für den Abgleich (ADR-0022 D1). Ein Verzeichnislauf ist kein
#: Mensch vor einem Formular: der Agent liest je nach Grösse Minuten. Muss
#: unter der Frist liegen, die die Konsole diesem Auftrag gibt (dort 10
#: Minuten) — sonst wartet die Datenebene auf etwas, das schon verfallen ist.
SEARCH_TIMEOUT_S = 480.0

#: Obergrenze der Antwort eines Abgleichs. Darüber wird **abgewiesen** und
#: nicht abgeschnitten: ein halber Abgleich sieht aus wie ein ganzer und
#: behandelt am Ende Konten als verschwunden, die es noch gibt.
MAX_SEARCH_RECORDS = 50_000


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

    def _timeout_for(self, method: str) -> float:
        """Wartezeit für diese Methode.

        Alles ausser dem Abgleich ist eine Operation, auf die ein Mensch
        wartet; dafür ist eine Minute grosszügig. Der Abgleich ist ein Lauf
        über das ganze Verzeichnis und braucht seine eigene Zahl.
        """
        if method == "search_users":
            return max(self._timeout_s, SEARCH_TIMEOUT_S)
        return self._timeout_s

    async def _await_result(self, job_id: str, method: str) -> Any:
        url = f"{self._base}/api/tenants/{self._tenant_id}/jobs/{job_id}"
        timeout_s = self._timeout_for(method)
        deadline = time.monotonic() + timeout_s
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
                    timeout_s,
                    state or "unbekannt",
                )
                raise AdUnavailableError("connector_timeout")
            await asyncio.sleep(POLL_INTERVAL_S)

    # -- Abgleich ---------------------------------------------------------
    async def search_users(
        self,
        *,
        search_base: str | None = None,
        attributes: Sequence[str] = DEFAULT_USER_ATTRIBUTES,
        changed_since: datetime | None = None,
    ) -> list[AdUserRecord]:
        """Das Verzeichnis lesen — über den Agenten (ADR-0022 D1).

        Die einzige Methode, die **nur** dieser Rücken anbietet. Der
        RPC-Rücken erbt absichtlich weiter den direkten Körper: im
        Container-Split läuft der Abgleich im AD-Container selbst, und ein
        Aufruf von aussen soll dort laut scheitern (ADR-0011).

        Ohne diese Überschreibung erbte der Connector-Rücken denselben
        direkten Körper — und die Plattform griffe beim Abgleich eines
        gehosteten Kunden per LDAP in sein Netz. Genau die Verbindung, die es
        nach ADR-0014 nicht geben darf.
        """
        base = search_base or self._settings.ad_users_search_base
        if not base:
            raise AdUnavailableError("MAGISTER_AD_USERS_SEARCH_BASE is not configured")
        raw = await self._call(
            "search_users",
            {
                "search_base": base,
                "attributes": list(attributes),
                # ISO-8601 und kein Zeitstempel: der Auftrag geht als JSON
                # durch die Konsole, und der Agent baut daraus wieder ein
                # `datetime`.
                "changed_since": changed_since.isoformat() if changed_since else None,
            },
        )
        if not isinstance(raw, list):
            raise AdUnavailableError("connector_search_malformed")
        records = cast(list[Any], raw)
        if len(records) > MAX_SEARCH_RECORDS:
            # Ehrlich abweisen statt kürzen. Der nächste Schritt steht in der
            # Meldung, weil sie im Protokoll des Kunden landet.
            raise AdUnavailableError(
                f"connector_search_too_large: {len(records)} Konten über der Grenze von "
                f"{MAX_SEARCH_RECORDS}. Suchbasis enger fassen oder inkrementell abgleichen."
            )
        try:
            return [ad_user_record_from_jsonable(item) for item in records]
        except (TypeError, ValueError, KeyError) as exc:
            # Ein Agent mit anderem Stand schickt ein Feld zu viel oder zu
            # wenig. Das ist ein Ausfall dieses Rückens, kein Programmfehler
            # der Fachschicht — dieselbe Ausnahme wie ein Netzproblem.
            raise AdUnavailableError("connector_search_malformed") from exc


__all__ = ["AdConnectorClient"]
