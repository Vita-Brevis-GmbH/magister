"""Der Abrufbetrieb (ADR-0014).

Geprüft wird das Zusammenspiel: abholen, gegen die lokalen Grenzen prüfen,
ausführen, signiert antworten. Und vor allem die Fälle, in denen der Agent
*nicht* ausführt — ein lokal abgelehnter Auftrag muss trotzdem beantwortet
werden, sonst wartet die Plattform auf etwas, das nie kommt.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest

from connector_agent.config import AgentConfig, AgentSecrets
from connector_agent.guardrails import Guardrails
from connector_agent.renewal import RETRY_AFTER, RenewalError, RenewalResult
from connector_agent.runner import AdExecutor, Runner
from connector_agent.signing import canonical_result_body, sign_result
from tests.helpers import FakeCa, write_enrolled_state

SCHULE = "OU=Schule,DC=gemeinde,DC=local"
LEHRER = f"CN=Muster,OU=Lehrer,{SCHULE}"
HMAC_KEY = "hmac-schluessel"


class FakeAd:
    """AD-Attrappe: hält fest, was aufgerufen wurde."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_on: str | None = None

    async def find_user_dn(self, ad_object_guid: str) -> str:
        self.calls.append(("find_user_dn", {"ad_object_guid": ad_object_guid}))
        if self.raise_on == "find_user_dn":
            raise RuntimeError("Verzeichnis sagt nein: CN=Geheim,OU=Intern")
        return LEHRER

    async def probe_service_connection_detailed(self) -> tuple[bool, str]:
        self.calls.append(("probe_service_connection_detailed", {}))
        return True, "ok"

    async def modify_password(self, *, user_dn: str, new_password: str, force_change: bool) -> None:
        self.calls.append(("modify_password", {"user_dn": user_dn, "force_change": force_change}))


class FakePlatform:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs
        self.results: list[dict[str, Any]] = []
        self.poll_status = 200
        self.result_status = 200

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                if self.poll_status != 200:
                    return httpx.Response(self.poll_status, json={"detail": "nope"})
                jobs, self.jobs = self.jobs, []
                return httpx.Response(200, json=jobs)
            body = json.loads(request.content)
            body["_job_id"] = request.url.path.split("/")[-2]
            self.results.append(body)
            return httpx.Response(self.result_status, json={"state": "done"})

        return httpx.MockTransport(handler)


def _runner(tmp_path: Path, platform: FakePlatform, ad: FakeAd) -> Runner:
    # Echtes Zertifikat und echter Schlüssel: build_client lädt sie in einen
    # SSLContext. Mit Attrappen-Dateien wäre genau der Pfad übersprungen, an
    # dem httpx 0.28 sich anders verhält als seine Dokumentation.
    write_enrolled_state(tmp_path, FakeCa())
    config = AgentConfig.from_mapping(
        {
            "endpoint": "https://connect.magister.test:46200",
            "state_dir": str(tmp_path),
            "ca_bundle": str(tmp_path / "ca.pem"),
            "allowed_ous": [SCHULE],
        }
    )
    return Runner(
        config=config,
        secrets=AgentSecrets(agent_id="a", api_key="k", result_hmac_key=HMAC_KEY, spki_sha256="f"),
        executor=AdExecutor(ad),
        guardrails=Guardrails(allowed_ous=frozenset({SCHULE})),
        transport=platform.transport(),
    )


def _signature_is_valid(entry: dict[str, Any]) -> bool:
    body = canonical_result_body(ok=entry["ok"], result=entry["result"], error=entry["error"])
    return sign_result(HMAC_KEY, entry["_job_id"], body) == entry["signature"]


class TestExecution:
    async def test_a_job_is_executed_and_signed(self, tmp_path: Path) -> None:
        ad = FakeAd()
        platform = FakePlatform(
            [{"id": "job-1", "method": "find_user_dn", "payload": {"ad_object_guid": "g"}}]
        )
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            assert await runner.run_once(client) == 1
        assert ad.calls == [("find_user_dn", {"ad_object_guid": "g"})]
        assert platform.results[0]["ok"] is True
        assert platform.results[0]["result"] == LEHRER
        assert _signature_is_valid(platform.results[0])

    async def test_a_tuple_result_becomes_a_list(self, tmp_path: Path) -> None:
        # Sonst passt die HMAC nicht: das Tupel wird beim Serialisieren zur
        # Liste, und die Signatur würde über andere Bytes gerechnet.
        ad = FakeAd()
        platform = FakePlatform(
            [{"id": "job-2", "method": "probe_service_connection_detailed", "payload": {}}]
        )
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            await runner.run_once(client)
        assert platform.results[0]["result"] == [True, "ok"]
        assert _signature_is_valid(platform.results[0])

    async def test_a_write_reaches_the_directory(self, tmp_path: Path) -> None:
        ad = FakeAd()
        platform = FakePlatform(
            [
                {
                    "id": "job-3",
                    "method": "modify_password",
                    "payload": {
                        "user_dn": LEHRER,
                        "new_password": "Geheim-123",
                        "force_change": True,
                    },
                }
            ]
        )
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            await runner.run_once(client)
        assert ad.calls[0][0] == "modify_password"
        assert platform.results[0]["ok"] is True
        # Das Passwort darf nicht im Ergebnis auftauchen.
        assert "Geheim-123" not in json.dumps(platform.results)


class TestRefusalsAreStillAnswered:
    async def test_a_guardrail_violation_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        """Abgelehnt, aber beantwortet.

        Sonst wartet die Plattform 90 Sekunden auf einen Auftrag, den der Agent
        nie ausführen wird — und der Anwender sieht einen Timeout statt einer
        Aussage.
        """
        ad = FakeAd()
        platform = FakePlatform(
            [
                {
                    "id": "job-4",
                    "method": "modify_password",
                    "payload": {"user_dn": "CN=Admin,CN=Users,DC=gemeinde,DC=local"},
                }
            ]
        )
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            await runner.run_once(client)
        assert ad.calls == [], "der Auftrag darf das AD nicht erreichen"
        assert platform.results[0]["ok"] is False
        assert "ausserhalb" in platform.results[0]["error"]
        assert _signature_is_valid(platform.results[0])

    async def test_an_ad_error_does_not_leak_directory_content(self, tmp_path: Path) -> None:
        """Der Fehlertext kann einen DN enthalten, also Personenbezug.

        Er gehört ins lokale Protokoll beim Kunden; an die Plattform geht nur
        der Ausnahmetyp.
        """
        ad = FakeAd()
        ad.raise_on = "find_user_dn"
        platform = FakePlatform(
            [{"id": "job-5", "method": "find_user_dn", "payload": {"ad_object_guid": "g"}}]
        )
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            await runner.run_once(client)
        assert platform.results[0]["ok"] is False
        assert platform.results[0]["error"] == "RuntimeError"
        assert "CN=Geheim" not in json.dumps(platform.results)

    async def test_an_unknown_method_never_reaches_getattr(self, tmp_path: Path) -> None:
        # Die Grenze greift VOR dem getattr — sonst wäre der Methodenname aus
        # einem Auftrag ein Weg, beliebige Attribute anzusprechen.
        ad = FakeAd()
        platform = FakePlatform([{"id": "job-6", "method": "__init__", "payload": {}}])
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            await runner.run_once(client)
        assert ad.calls == []
        assert platform.results[0]["ok"] is False


class TestPlatformStates:
    async def test_a_401_stops_the_round(self, tmp_path: Path) -> None:
        platform = FakePlatform([])
        platform.poll_status = 401
        runner = _runner(tmp_path, platform, FakeAd())
        async with runner.build_client() as client:
            with pytest.raises(PermissionError, match="widerrufen"):
                await runner.run_once(client)

    async def test_a_409_on_the_result_is_not_an_error(self, tmp_path: Path) -> None:
        # Der Auftrag ist verfallen, während der Agent gearbeitet hat. Kein
        # Fehler des Agenten, und kein Grund abzubrechen.
        ad = FakeAd()
        platform = FakePlatform(
            [{"id": "job-7", "method": "find_user_dn", "payload": {"ad_object_guid": "g"}}]
        )
        platform.result_status = 409
        runner = _runner(tmp_path, platform, ad)
        async with runner.build_client() as client:
            assert await runner.run_once(client) == 1

    async def test_an_empty_poll_is_fine(self, tmp_path: Path) -> None:
        platform = FakePlatform([])
        runner = _runner(tmp_path, platform, FakeAd())
        async with runner.build_client() as client:
            assert await runner.run_once(client) == 0


class TestRenewalScheduling:
    """Wann der Runner erneuert — und wie oft er es versucht (ADR-0014).

    Das Zertifikat gilt 90 Tage; erneuert wird 30 Tage vor Ablauf. Die beiden
    Fragen, die hier entschieden werden, sind betrieblich die wichtigeren:

    * **Wie oft wird es versucht, wenn es scheitert?** Bei jedem Long-Poll
      wären es ein paar tausend Versuche am Tag gegen einen Endpunkt, der eine
      CA bemüht. Deshalb höchstens einer pro Stunde.
    * **Bleibt der Agent währenddessen arbeitsfähig?** Ja — das bestehende
      Zertifikat gilt noch einen Monat. Eine gescheiterte Erneuerung darf den
      Abrufbetrieb nicht anhalten.
    """

    def test_a_fresh_certificate_needs_no_renewal(self, tmp_path: Path) -> None:
        runner = _runner(tmp_path, FakePlatform([]), FakeAd())
        assert runner.renewal_due() is False

    def test_an_expiring_certificate_is_due(self, tmp_path: Path) -> None:
        runner = _runner(tmp_path, FakePlatform([]), FakeAd())
        # Die Attrappen-CA stellt für 90 Tage aus; 61 Tage später sind es 29.
        soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=61)
        assert runner.renewal_due(now=soon) is True

    def test_a_failed_attempt_is_not_repeated_immediately(self, tmp_path: Path) -> None:
        """Sonst klopft der Agent bei jedem Long-Poll erneut an."""
        runner = _runner(tmp_path, FakePlatform([]), FakeAd())
        soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=61)
        runner.last_renewal_attempt = soon
        assert runner.renewal_due(now=soon + dt.timedelta(minutes=5)) is False
        assert runner.renewal_due(now=soon + RETRY_AFTER + dt.timedelta(minutes=1)) is True

    @pytest.mark.asyncio
    async def test_a_failed_renewal_does_not_stop_the_agent(self, tmp_path: Path) -> None:
        """Das bestehende Zertifikat gilt noch einen Monat.

        Ein Agent, der wegen einer gescheiterten Erneuerung aufhört, Aufträge
        abzuholen, tauscht ein Problem in vier Wochen gegen einen Ausfall
        jetzt.
        """
        platform = FakePlatform([])
        ad = FakeAd()
        runner = _runner(tmp_path, platform, ad)
        soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=61)

        def refuse(*args: object, **kwargs: object) -> object:
            raise RenewalError("Plattform nicht erreichbar")

        with monkeypatched(renewal_module="connector_agent.runner", renew=refuse):
            assert await runner.maybe_renew(now=soon) is False
        # Der Versuch ist vermerkt, damit er nicht sofort wiederholt wird.
        assert runner.last_renewal_attempt == soon

    @pytest.mark.asyncio
    async def test_a_successful_renewal_updates_the_fingerprint(self, tmp_path: Path) -> None:
        """Der Runner trägt den neuen Fingerprint mit.

        Er steht in ``secrets``, und der Client baut daraus nichts — aber der
        Fingerprint wandert in ``secrets.json`` und ist die Antwort auf die
        Frage „mit welchem Schlüssel arbeitet dieser Agent gerade".
        """
        runner = _runner(tmp_path, FakePlatform([]), FakeAd())
        soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=61)

        def succeed(*args: object, **kwargs: object) -> RenewalResult:
            return RenewalResult(
                spki_sha256="b" * 64,
                certificate_not_after=dt.datetime.now(dt.UTC) + dt.timedelta(days=90),
            )

        with monkeypatched(renewal_module="connector_agent.runner", renew=succeed):
            assert await runner.maybe_renew(now=soon) is True
        assert runner.secrets.spki_sha256 == "b" * 64


@contextlib.contextmanager
def monkeypatched(*, renewal_module: str, renew: object) -> Generator[None]:
    """``renew`` im Runner-Modul austauschen.

    Kein ``monkeypatch``-Fixture, weil diese Tests teils synchron und teils
    asynchron sind und der Kontextmanager an beiden Stellen gleich aussieht.
    """
    import importlib

    module = importlib.import_module(renewal_module)
    original = module.renew
    module.renew = renew  # type: ignore[assignment]
    try:
        yield
    finally:
        module.renew = original  # type: ignore[assignment]
