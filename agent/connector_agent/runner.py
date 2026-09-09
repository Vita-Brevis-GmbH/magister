"""Der Abrufbetrieb des Agenten (ADR-0014).

Long-Poll holen, gegen die lokalen Grenzen prüfen, gegen das AD ausführen,
Ergebnis mit HMAC zurückgeben. Danach wieder von vorn.

Die AD-Operationen kommen aus ``magister_api.ad`` — **derselbe** Code, den
Magister auch direkt benutzt. Das ist Absicht: siebzehn LDAP-Operationen ein
zweites Mal zu schreiben hiesse, zwei Stände zu pflegen, von denen einer
schlechter getestet ist. Der Preis ist eine Abhängigkeit auf das Paket; dafür
ist die AD-Schicht seit ADR-0014 frei von FastAPI (siehe
``magister_api/ad/threadpool.py``).

Was der Agent **nicht** tut: Aufträge zwischenspeichern, wiederholen oder
umsortieren. Ein Auftrag wird einmal ausgeführt und beantwortet. Verfällt er
unterwegs, weist die Plattform das Ergebnis ab — richtig so: ein spät
ausgeführter Passwort-Reset setzte das alte Passwort, nachdem der Anwender
längst ein neues gewählt hat.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, cast

import httpx

from connector_agent.config import AgentConfig, AgentSecrets
from connector_agent.guardrails import Guardrails, GuardrailViolationError
from connector_agent.renewal import (
    RETRY_AFTER,
    RenewalError,
    days_until_expiry,
    is_due,
    renew,
)
from connector_agent.signing import canonical_result_body, sign_result
from connector_agent.tls import build_context

logger = logging.getLogger(__name__)

#: Methoden ohne Argumente. Sie werden ohne Nutzlast aufgerufen.
_NO_ARG_METHODS = frozenset({"probe_service_connection", "probe_service_connection_detailed"})

#: Methoden, die ihr erstes Argument positionell nehmen.
_POSITIONAL_FIRST: dict[str, str] = {
    "find_user_dn": "ad_object_guid",
    "fetch_user_groups": "ad_object_guid",
}


#: Form einer AD-Operation: async, beliebige Argumente, beliebiges Ergebnis.
#: Genauer geht nicht, weil die siebzehn Methoden verschiedene Signaturen
#: haben — die Prüfung der Argumente macht die Gegenseite (``AdClient``), die
#: Prüfung des *Namens* macht die Allowlist davor.
AdOperation = Callable[..., Awaitable[Any]]


class AdExecutor:
    """Führt eine Methode der Allowlist gegen das lokale AD aus.

    Der Aufruf geht über ``getattr`` — aber **erst nachdem** die Grenzen
    geprüft sind. Ohne diese Reihenfolge wäre der Methodenname aus einem
    Auftrag ein Weg, beliebige Attribute des Clients aufzurufen.
    """

    def __init__(self, ad: object) -> None:
        self._ad = ad

    async def run(self, method: str, payload: dict[str, Any]) -> Any:
        raw = getattr(self._ad, method, None)
        if raw is None or not callable(raw):
            raise GuardrailViolationError(f"Der AD-Client kennt {method!r} nicht.")
        fn = cast(AdOperation, raw)
        if method in _NO_ARG_METHODS:
            return await fn()
        positional = _POSITIONAL_FIRST.get(method)
        if positional is not None:
            return await fn(payload[positional])
        return await fn(**payload)


@dataclass(slots=True)
class Runner:
    config: AgentConfig
    secrets: AgentSecrets
    executor: AdExecutor
    guardrails: Guardrails
    agent_version: str = "0.1.0"
    #: Injektionsnaht für Tests; sonst baut der Runner seinen eigenen Client.
    transport: httpx.AsyncBaseTransport | None = None
    #: Wann zuletzt eine Erneuerung versucht wurde. Begrenzt die Versuche auf
    #: einen pro ``RETRY_AFTER``; sonst wären es bei jedem Long-Poll einer,
    #: also ein paar tausend am Tag gegen einen Endpunkt, der eine CA bemüht.
    last_renewal_attempt: dt.datetime | None = None

    def build_client(self) -> httpx.AsyncClient:
        # Client-Zertifikat: die eine Hälfte der Authentisierung. Die andere
        # ist der API-Key im Header. Beide zeigen auf dieselbe Agent-Zeile.
        #
        # Über einen ausdrücklichen SSLContext, nicht über verify=/cert=: die
        # naheliegende Schreibweise schickt seit httpx 0.28 kein Zertifikat
        # mehr, und zwar lautlos — die Gegenseite antwortet dann mit 401, als
        # hätte man keines. Siehe connector_agent/tls.py.
        context = build_context(
            ca_bundle=self.config.ca_bundle,
            cert=self.config.cert_path,
            key=self.config.key_path,
        )
        return httpx.AsyncClient(
            base_url=self.config.endpoint,
            timeout=httpx.Timeout(self.config.poll_seconds + 15.0),
            verify=context,
            # trust_env=False: kein Proxy aus der Umgebung. Über diesen Kanal
            # geht ein Client-Zertifikat, und ob es ankommt, darf nicht davon
            # abhängen, was in einem Profil steht. Braucht der Kunde einen
            # Proxy, steht er in der Konfiguration.
            trust_env=False,
            proxy=self.config.proxy,
            transport=self.transport,
            headers={
                "X-Connector-Api-Key": self.secrets.api_key,
                "User-Agent": f"magister-connector-agent/{self.agent_version}",
            },
        )

    async def run_once(self, client: httpx.AsyncClient) -> int:
        """Eine Runde: abholen, ausführen, antworten. Rückgabe: Anzahl Aufträge."""
        resp = await client.get("/connector/jobs")
        if resp.status_code == 401:
            # Widerrufen, gesperrt oder falscher Key. Kein Grund für einen
            # schnellen Wiederholungslauf — das behebt sich nicht von selbst.
            raise PermissionError(
                "Die Plattform hat den Agenten abgewiesen (401). Ist er in der "
                "Konsole widerrufen oder der Kunde gesperrt?"
            )
        resp.raise_for_status()
        jobs: list[dict[str, Any]] = resp.json()
        for job in jobs:
            await self._handle(client, job)
        return len(jobs)

    async def _handle(self, client: httpx.AsyncClient, job: dict[str, Any]) -> None:
        job_id = str(job.get("id", ""))
        method = str(job.get("method", ""))
        raw_payload: object = job.get("payload")
        payload: dict[str, Any] = (
            cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
        )
        try:
            self.guardrails.check(method, payload)
        except GuardrailViolationError as exc:
            # Abgelehnt, aber beantwortet: die Plattform soll den Grund sehen
            # und nicht auf einen Auftrag warten, der nie ausgeführt wird.
            logger.warning("Auftrag %s (%s) lokal abgelehnt: %s", job_id, method, exc)
            await self._report(client, job_id, ok=False, result=None, error=str(exc))
            return
        try:
            result = await self.executor.run(method, payload)
        except Exception as exc:
            # Der Text kann einen DN enthalten, also Personenbezug. Er geht in
            # das lokale Protokoll beim Kunden; an die Plattform geht nur der
            # Ausnahmetyp.
            logger.warning("Auftrag %s (%s) gescheitert: %s", job_id, method, exc)
            await self._report(client, job_id, ok=False, result=None, error=type(exc).__name__)
            return
        await self._report(client, job_id, ok=True, result=_jsonable(result), error=None)
        logger.info("Auftrag %s (%s) ausgeführt", job_id, method)

    async def _report(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        *,
        ok: bool,
        result: Any,
        error: str | None,
    ) -> None:
        body = canonical_result_body(ok=ok, result=result, error=error)
        signature = sign_result(self.secrets.result_hmac_key, job_id, body)
        resp = await client.post(
            f"/connector/jobs/{job_id}/result",
            json={"ok": ok, "result": result, "error": error, "signature": signature},
        )
        if resp.status_code == 409:
            # Verfallen, während wir gearbeitet haben. Kein Fehler des Agenten.
            logger.warning(
                "Ergebnis für Auftrag %s wurde nicht mehr angenommen (verfallen).", job_id
            )
            return
        if resp.status_code != 200:
            logger.warning("Ergebnis für Auftrag %s abgelehnt: HTTP %s", job_id, resp.status_code)

    # -- Zertifikatserneuerung -------------------------------------------
    def renewal_due(self, *, now: dt.datetime | None = None) -> bool:
        """Ist eine Erneuerung fällig und der letzte Versuch lang genug her?"""
        moment = now or dt.datetime.now(dt.UTC)
        last = self.last_renewal_attempt
        if last is not None and moment - last < RETRY_AFTER:
            return False
        return is_due(self.config.cert_path, now=moment)

    async def maybe_renew(self, *, now: dt.datetime | None = None) -> bool:
        """Erneuern, wenn fällig. ``True``, wenn ein neues Zertifikat da ist.

        Läuft über ``asyncio.to_thread``: ``renew`` benutzt einen
        **synchronen** httpx-Client, weil es dieselbe Naht wie ``enroll`` ist
        und die von der Kommandozeile aus aufgerufen wird. Ihn hier direkt
        aufzurufen hiesse, die Ereignisschleife für die Dauer eines
        CA-Aufrufs anzuhalten — und damit auch jeden laufenden Auftrag.
        """
        if not self.renewal_due(now=now):
            return False
        self.last_renewal_attempt = now or dt.datetime.now(dt.UTC)
        try:
            days = days_until_expiry(self.config.cert_path)
            logger.info("Zertifikat läuft in %.1f Tagen ab — Erneuerung wird versucht.", days)
        except RenewalError:
            logger.warning("Zertifikat nicht lesbar — Erneuerung wird versucht.")
        try:
            result = await asyncio.to_thread(
                renew,
                self.config,
                self.secrets,
                agent_version=self.agent_version,
            )
        except RenewalError as exc:
            # Kein Abbruch: das bestehende Zertifikat gilt noch (erneuert wird
            # 30 Tage vor Ablauf). Der Versuch wiederholt sich stündlich, und
            # ein Mensch hat einen Monat Zeit.
            logger.warning("Erneuerung gescheitert, wird wiederholt: %s", exc)
            return False
        self.secrets = replace(self.secrets, spki_sha256=result.spki_sha256)
        return True

    async def serve_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            # Der Client trägt das Zertifikat in seinem SSL-Kontext. Nach einer
            # Erneuerung muss er also neu gebaut werden — deshalb die äussere
            # Schleife. Ein httpx-Client lässt seinen Kontext nicht
            # nachträglich austauschen, und ein Neustart des Dienstes wäre die
            # Alternative gewesen.
            renewed = False
            async with self.build_client() as client:
                while not stop.is_set() and not renewed:
                    try:
                        renewed = await self.maybe_renew()
                        if renewed:
                            logger.info("Verbindung wird mit dem neuen Zertifikat neu aufgebaut.")
                            break
                        await self.run_once(client)
                    except PermissionError as exc:
                        logger.error("%s", exc)
                        # Lange warten: das behebt ein Mensch in der Konsole.
                        await _sleep_or_stop(stop, 60.0)
                    except (httpx.HTTPError, OSError) as exc:
                        logger.warning("Plattform nicht erreichbar: %s", exc)
                        await _sleep_or_stop(stop, self.config.backoff_seconds)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return


def _jsonable(value: Any) -> Any:
    """Ergebnis in JSON-taugliche Form bringen.

    Tupel werden zu Listen (``probe_service_connection_detailed`` gibt eines
    zurück), Mengen zu sortierten Listen. Alles andere muss schon passen —
    sonst fliegt es hier auf und nicht erst als kaputte HMAC.
    """
    if isinstance(value, tuple):
        return [_jsonable(item) for item in cast(tuple[Any, ...], value)]
    if isinstance(value, set | frozenset):
        return sorted(_jsonable(item) for item in cast(frozenset[Any], value))
    if isinstance(value, list):
        return [_jsonable(item) for item in cast(list[Any], value)]
    if isinstance(value, dict):
        items = cast(dict[Any, Any], value).items()
        return {str(key): _jsonable(item) for key, item in items}
    json.dumps(value)  # wirft, wenn es nicht serialisierbar ist
    return value


__all__ = ["AdExecutor", "AdOperation", "Runner"]
