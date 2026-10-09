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
from dataclasses import dataclass, field, replace
from typing import Any, cast

import httpx

from connector_agent import remote as remote_cfg
from connector_agent.config import AgentConfig, AgentSecrets
from connector_agent.diagnose import explain_transport_error
from connector_agent.guardrails import (
    MUTATING_USER_METHODS,
    Guardrails,
    GuardrailViolationError,
)
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

#: Aufträge, auf die kein Mensch wartet und die Minuten dauern: der Abgleich.
#: Sie laufen im Hintergrund, höchstens einer zur Zeit, und blockieren die
#: Abholung nicht. Wörtlich wie ``BULK_METHODS`` in der Konsole.
BULK_METHODS: frozenset[str] = frozenset(
    {"search_users", "search_groups", "search_computers", "search_managed_computers"}
)

#: Wartezeit eines Polls, solange eine Suche läuft.
BUSY_POLL_SECONDS = 1

#: Methoden ohne Argumente. Sie werden ohne Nutzlast aufgerufen.
_NO_ARG_METHODS = frozenset({"probe_service_connection", "probe_service_connection_detailed"})

#: Methoden, die ihr erstes Argument positionell nehmen.
_POSITIONAL_FIRST: dict[str, str] = {
    "find_user_dn": "ad_object_guid",
    "fetch_user_groups": "ad_object_guid",
}


def _decode_search_users(payload: dict[str, Any]) -> dict[str, Any]:
    """`changed_since` von ISO-8601 zurück in ein `datetime`.

    Ein Auftrag reist als JSON; JSON kennt keinen Zeitstempel. Ohne diese
    Umkehr bekäme `search_users` eine Zeichenkette und baute daraus einen
    LDAP-Filter aus dem Wort „None" — also einen Vollabgleich, jedes Mal.
    """
    decoded = dict(payload)
    raw = decoded.get("changed_since")
    decoded["changed_since"] = dt.datetime.fromisoformat(raw) if isinstance(raw, str) else None
    return decoded


#: Nutzlasten, die vor dem Aufruf zurückübersetzt werden müssen.
_PAYLOAD_DECODERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "search_users": _decode_search_users,
}


def _encode_user_records(result: Any) -> Any:
    """`AdUserRecord`-Liste in JSON-taugliche Form (ADR-0022 D4).

    Die Umwandlung ist die, die es für den RPC-Weg schon gibt — zwei Kodierer
    für dasselbe Format wären zwei Stände. Ohne sie scheiterte der Auftrag
    beim Signieren statt beim Kodieren, und die Meldung hiesse „nicht
    serialisierbar" statt „Abgleich".
    """
    from magister_api.ad.rpc import ad_user_record_to_jsonable

    records = cast(list[Any], result)
    return [ad_user_record_to_jsonable(record) for record in records]


def _encode_group_records(result: Any) -> Any:
    """`AdGroupRecord`-Liste in JSON-taugliche Form, wie beim RPC-Weg."""
    from magister_api.ad.rpc import ad_group_record_to_jsonable

    return [ad_group_record_to_jsonable(record) for record in cast(list[Any], result)]


#: Ergebnisse, die vor dem Zurückschicken übersetzt werden müssen.
_RESULT_ENCODERS: dict[str, Callable[[Any], Any]] = {
    "search_users": _encode_user_records,
    "search_groups": _encode_group_records,
}


def _identity(item: Any) -> str:
    """Woran ein Objekt in einem Suchergebnis erkannt wird: DN, sonst GUID."""
    dn: object = getattr(item, "distinguished_name", None)
    if isinstance(dn, str) and dn:
        return dn.lower()
    if isinstance(item, tuple):
        first: object = cast(tuple[object, ...], item)[0] if item else ""
        return str(first).lower()
    return repr(item)


def _merge_results(parts: list[Any]) -> Any:
    """Ergebnisse mehrerer Such-Basen zu einem zusammenführen.

    Listen werden aneinandergehängt, doppelte Objekte (verschachtelte
    Freigaben) einmal behalten — erkannt am DN bzw. an der GUID. Dicts
    (``managedBy``-Zuordnung) werden vereinigt.
    """
    if all(isinstance(p, dict) for p in parts):
        merged: dict[Any, Any] = {}
        for part in parts:
            merged.update(cast(dict[Any, Any], part))
        return merged
    seen: set[str] = set()
    out: list[Any] = []
    for part in parts:
        for item in cast(list[Any], part):
            key = _identity(item)
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


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

    async def _refuse_privileged(self, method: str, payload: dict[str, Any]) -> None:
        """Geschützte Konten (``adminCount=1``) fasst der Agent nicht an.

        Im AD nachgesehen und nicht im Auftrag: ob ein Konto privilegiert ist,
        ist eine Eigenschaft des Kontos. Scheitert die Prüfung, scheitert der
        Auftrag — ohne Antwort auf die Frage wird nicht geschrieben.
        """
        if method not in MUTATING_USER_METHODS:
            return
        user_dn: object = payload.get("user_dn")
        if not isinstance(user_dn, str) or not user_dn:
            return
        check = getattr(self._ad, "is_privileged_account", None)
        if check is None or not callable(check):
            raise GuardrailViolationError(
                "Der AD-Client kann geschützte Konten nicht erkennen; der Agent schreibt "
                "deshalb nichts."
            )
        if await cast(AdOperation, check)(user_dn=user_dn):
            raise GuardrailViolationError(
                f"Das Zielkonto ist ein geschütztes AD-Konto (adminCount) — {method} wird "
                "vom Agenten nicht ausgeführt."
            )

    async def run(self, method: str, payload: dict[str, Any]) -> Any:
        raw = getattr(self._ad, method, None)
        if raw is None or not callable(raw):
            raise GuardrailViolationError(f"Der AD-Client kennt {method!r} nicht.")
        await self._refuse_privileged(method, payload)
        fn = cast(AdOperation, raw)
        if method in _NO_ARG_METHODS:
            return await fn()
        positional = _POSITIONAL_FIRST.get(method)
        if positional is not None:
            return await fn(payload[positional])
        decoder = _PAYLOAD_DECODERS.get(method)
        if decoder is not None:
            payload = decoder(payload)
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
    #: Die Konfiguration aus dem Cockpit, mit der der Runner gestartet ist.
    #: ``None`` heisst: kein Nachladen (Tests mit festen Grenzen).
    remote: remote_cfg.RemoteConfig | None = None
    #: Baut den AD-Zugang neu, wenn das Cockpit ihn ändert (andere DCs,
    #: Suchbasis, CA). ``None`` gibt zurück, wer ihn nicht bauen konnte.
    executor_factory: Callable[[remote_cfg.RemoteConfig], AdExecutor | None] | None = None
    #: Monotone Zeit des letzten Abrufs der Konfiguration.
    last_refresh: float | None = None
    #: Der laufende Abgleich, falls einer läuft (siehe :data:`BULK_METHODS`).
    bulk_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    @property
    def bulk_running(self) -> bool:
        return self.bulk_task is not None and not self.bulk_task.done()

    async def drain(self) -> None:
        """Auf einen laufenden Abgleich warten — vor dem Schliessen des Clients."""
        task, self.bulk_task = self.bulk_task, None
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

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
        """Eine Runde: abholen, ausführen, antworten. Rückgabe: Anzahl Aufträge.

        Ein Abgleich läuft im Hintergrund weiter, während diese Runde schon
        die nächsten Aufträge holt: ein Passwort-Reset soll nach Sekunden im
        AD sein und nicht nach dem Abgleich. Solange einer läuft, fragt der
        Agent mit ``bulk=false`` nur nach interaktiven Aufträgen.
        """
        busy = self.bulk_running
        # Solange eine Suche läuft, kurz fragen: ist sie fertig, soll die
        # nächste Suche des Abgleichs sofort kommen und nicht erst nach dem
        # Ende eines 25-Sekunden-Polls, der sie nicht ausliefern darf.
        params = {"bulk": "false", "wait_seconds": str(BUSY_POLL_SECONDS)} if busy else None
        resp = await client.get("/connector/jobs", params=params)
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
            if str(job.get("method", "")) in BULK_METHODS and not self.bulk_running:
                self.bulk_task = asyncio.create_task(self._handle_logged(client, job))
            else:
                # Auch ein zweiter Abgleich, falls eine ältere Konsole `bulk`
                # nicht kennt: dann eben der Reihe nach, wie bisher.
                await self._handle(client, job)
        return len(jobs)

    async def _handle_logged(self, client: httpx.AsyncClient, job: dict[str, Any]) -> None:
        """Wie :meth:`_handle`, aber für den Hintergrund: nichts geht verloren."""
        try:
            await self._handle(client, job)
        except Exception as exc:
            # Ohne das verschwände ein Fehler beim Zurückmelden in einer
            # Task, die niemand mehr ansieht.
            logger.warning("Abgleich %s nicht zurückgemeldet: %s", job.get("id"), exc)

    async def _handle(self, client: httpx.AsyncClient, job: dict[str, Any]) -> None:
        job_id = str(job.get("id", ""))
        method = str(job.get("method", ""))
        raw_payload: object = job.get("payload")
        payload: dict[str, Any] = (
            cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
        )
        payloads = [payload]
        base: object = payload.get("search_base")
        if method in BULK_METHODS and isinstance(base, str) and base:
            bases = self.guardrails.narrow_search_base(base)
            if bases != [base]:
                logger.info(
                    "Auftrag %s (%s): Such-Basis auf %d freigegebene OU(s) eingegrenzt",
                    job_id,
                    method,
                    len(bases),
                )
                payloads = [{**payload, "search_base": b} for b in bases]
        try:
            for part in payloads:
                self.guardrails.check(method, part)
        except GuardrailViolationError as exc:
            # Abgelehnt, aber beantwortet: die Plattform soll den Grund sehen
            # und nicht auf einen Auftrag warten, der nie ausgeführt wird.
            logger.warning("Auftrag %s (%s) lokal abgelehnt: %s", job_id, method, exc)
            await self._report(client, job_id, ok=False, result=None, error=str(exc))
            return
        try:
            parts = [await self.executor.run(method, part) for part in payloads]
            result = parts[0] if len(parts) == 1 else _merge_results(parts)
        except GuardrailViolationError as exc:
            # Eine Grenze, die erst im AD sichtbar wird (geschütztes Konto). Der
            # Text nennt die Regel, keinen DN — er darf an die Plattform.
            logger.warning("Auftrag %s (%s) lokal abgelehnt: %s", job_id, method, exc)
            await self._report(client, job_id, ok=False, result=None, error=str(exc))
            return
        except Exception as exc:
            # Der Text kann einen DN enthalten, also Personenbezug. Er geht in
            # das lokale Protokoll beim Kunden; an die Plattform geht nur der
            # Ausnahmetyp.
            logger.warning("Auftrag %s (%s) gescheitert: %s", job_id, method, exc)
            error = type(exc).__name__
            if error == "AdUnavailableError":
                # Die AD-Schicht wirft feste Codes (`ldap_search_failed:noSuchObject`)
                # ohne DN und ohne Host — die gehen mit, damit die Plattform eine
                # genaue Meldung zeigen kann statt „nicht erreichbar“.
                error = f"AdUnavailableError: {str(exc)[:200]}"
            await self._report(client, job_id, ok=False, result=None, error=error)
            return
        encoder = _RESULT_ENCODERS.get(method)
        encoded = encoder(result) if encoder is not None else result
        await self._report(client, job_id, ok=True, result=_jsonable(encoded), error=None)
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

    # -- Konfiguration aus dem Cockpit ------------------------------------
    async def maybe_refresh_config(
        self, client: httpx.AsyncClient, *, now: float | None = None
    ) -> bool:
        """Neue Fassung holen, wenn fällig. ``True``, wenn sich etwas geändert hat.

        Scheitert der Abruf, gilt die bisherige Fassung weiter — eine kurz
        nicht erreichbare Plattform ist kein Grund, Aufträge abzulehnen, die
        sie gleich wieder schicken wird.
        """
        if self.remote is None:
            return False
        moment = asyncio.get_running_loop().time() if now is None else now
        if (
            self.last_refresh is not None
            and moment - self.last_refresh < remote_cfg.REFRESH_SECONDS
        ):
            return False
        self.last_refresh = moment
        try:
            fresh, raw = await remote_cfg.fetch(client)
        except remote_cfg.RemoteConfigError as exc:
            logger.warning("%s Es gilt die bisherige Konfiguration.", exc)
            return False
        if fresh.revision and fresh.revision == self.remote.revision:
            return False
        remote_cfg.save_cache(self.config, raw)
        for dn, reason in fresh.refused_ous:
            logger.warning("OU-Freigabe aus dem Cockpit verworfen (%s): %s", reason, dn)
        if fresh.ad != self.remote.ad and self.executor_factory is not None:
            executor = self.executor_factory(fresh)
            if executor is None:
                logger.error(
                    "Neuer AD-Zugang aus dem Cockpit nicht nutzbar; es gilt der bisherige."
                )
            else:
                self.executor = executor
        self.guardrails = fresh.guardrails
        self.remote = fresh
        logger.info("%s", remote_cfg.describe(fresh))
        return True

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
                        await self.maybe_refresh_config(client)
                        await self.run_once(client)
                    except PermissionError as exc:
                        logger.error("%s", exc)
                        # Lange warten: das behebt ein Mensch in der Konsole.
                        await _sleep_or_stop(stop, 60.0)
                    except (httpx.HTTPError, OSError) as exc:
                        logger.warning("%s", explain_transport_error(exc, self.config))
                        await _sleep_or_stop(stop, self.config.backoff_seconds)
                # Der Abgleich benutzt denselben Client. Beim Anhalten wird er
                # abgebrochen (die Konsole lässt ihn verfallen), bei einer
                # Erneuerung zu Ende geführt.
                if stop.is_set() and self.bulk_task is not None:
                    self.bulk_task.cancel()
                await self.drain()


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


__all__ = ["BULK_METHODS", "AdExecutor", "AdOperation", "Runner"]
