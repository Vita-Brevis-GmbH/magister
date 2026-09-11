"""AD über den Connector-Agenten (ADR-0014), der dritte Rücken.

Geprüft wird vor allem, dass jeder Fehlweg als ``AdUnavailableError``
herauskommt: der Aufrufer im Fachcode soll einen unerreichbaren Agenten nicht
von einem AD-Ausfall unterscheiden müssen — er behandelt beides gleich, und die
bestehenden 503-Banner greifen ohne Änderung.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from magister_api.ad.client import AdUserRecord
from magister_api.ad.connector_client import (
    MAX_SEARCH_RECORDS,
    SEARCH_TIMEOUT_S,
    AdConnectorClient,
)
from magister_api.ad.errors import AdUnavailableError
from magister_api.ad.rpc import ad_user_record_to_jsonable
from magister_api.config import Settings

pytestmark = pytest.mark.asyncio

TENANT = "11111111-1111-1111-1111-111111111111"


def _settings() -> Settings:
    return Settings(
        audit_key=SecretStr("k"),
        session_secret=SecretStr("s"),
        csrf_secret=SecretStr("c"),
    )


class _Console:
    """Konsole als Attrappe. Hält die Aufträge und was daraus wurde."""

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.states: list[dict[str, Any]] = []
        self.enqueue_status = 201
        self.poll_status = 200
        self.seen_headers: dict[str, str] = {}

    def transport(self) -> httpx.MockTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.seen_headers = dict(request.headers)
            if request.method == "POST":
                self.enqueued.append(json.loads(request.content))
                if self.enqueue_status != 201:
                    return httpx.Response(self.enqueue_status, json={"detail": "nope"})
                return httpx.Response(201, json={"id": "job-1"})
            if self.poll_status != 200:
                return httpx.Response(self.poll_status, json={"detail": "nope"})
            body = self.states.pop(0) if self.states else {"state": "queued"}
            return httpx.Response(200, json=body)

        return httpx.MockTransport(handler)

    def client(self, **over: Any) -> AdConnectorClient:
        kwargs: dict[str, Any] = {
            "console_url": "https://console.magister.test:4444",
            "token": "service-token",
            "tenant_id": TENANT,
            "management_marker": "marker",
            "timeout_s": 0.05,
            "transport": self.transport(),
        }
        kwargs.update(over)
        return AdConnectorClient(_settings(), **kwargs)


class TestHappyPath:
    async def test_a_read_returns_the_agents_result(self) -> None:
        console = _Console()
        console.states = [{"state": "queued"}, {"state": "done", "result": "CN=Muster,OU=x"}]
        client = console.client()
        try:
            dn = await client.find_user_dn("guid-1")
        finally:
            await client.aclose()
        assert dn == "CN=Muster,OU=x"
        assert console.enqueued == [
            {"method": "find_user_dn", "payload": {"ad_object_guid": "guid-1"}}
        ]

    async def test_a_write_passes_its_payload_through(self) -> None:
        console = _Console()
        console.states = [{"state": "done", "result": None}]
        client = console.client()
        try:
            await client.modify_password(
                user_dn="CN=a", new_password="Geheim-123", force_change=True
            )
        finally:
            await client.aclose()
        assert console.enqueued[0]["method"] == "modify_password"
        assert console.enqueued[0]["payload"]["force_change"] is True

    async def test_it_speaks_to_the_console_with_token_and_marker(self) -> None:
        console = _Console()
        console.states = [{"state": "done", "result": None}]
        client = console.client()
        try:
            await client.probe_service_connection()
        finally:
            await client.aclose()
        assert console.seen_headers["authorization"] == "Bearer service-token"
        # Ohne den Marker verwirft die Konsole jede Anfrage (ADR-0015 D1).
        assert console.seen_headers["x-magister-management"] == "marker"

    async def test_a_tuple_result_survives_the_round_trip(self) -> None:
        # probe_service_connection_detailed gibt (bool, str) — über JSON wird
        # daraus eine Liste, und der Rücken muss sie wieder auspacken.
        console = _Console()
        console.states = [{"state": "done", "result": [True, "ok"]}]
        client = console.client()
        try:
            ok, reason = await client.probe_service_connection_detailed()
        finally:
            await client.aclose()
        assert (ok, reason) == (True, "ok")


class TestFailurePaths:
    """Jeder Weg endet als AdUnavailableError — sonst müsste jeder Aufrufer
    einen neuen Fehlerfall kennen."""

    async def test_an_unreachable_console_is_an_ad_outage(self) -> None:
        async def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("kein Netz")

        client = _Console().client(transport=httpx.MockTransport(boom))
        try:
            with pytest.raises(AdUnavailableError, match="connector_console_unreachable"):
                await client.find_user_dn("g")
        finally:
            await client.aclose()

    async def test_a_method_outside_the_allowlist_is_reported(self) -> None:
        console = _Console()
        console.enqueue_status = 400
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_method_not_allowed"):
                await client.find_user_dn("g")
        finally:
            await client.aclose()

    async def test_a_failed_job_does_not_leak_the_agents_text(self) -> None:
        """Der Fehlertext kommt aus dem Kundennetz — fremder Text.

        Er gehört ins Log, nicht als Fehlermeldung an den Browser. Der Aufrufer
        bekommt einen festen Schlüssel, den die Oberfläche übersetzt.
        """
        console = _Console()
        console.states = [{"state": "failed", "error": "LDAP sagt: <script>alert(1)</script>"}]
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError) as exc:
                await client.find_user_dn("g")
        finally:
            await client.aclose()
        assert str(exc.value) == "connector_job_failed"
        assert "script" not in str(exc.value)

    async def test_an_expired_job_says_the_agent_was_away(self) -> None:
        # Eigener Schlüssel, weil das betrieblich etwas anderes ist als ein
        # Fehler im AD: der Agent steht, nicht das Verzeichnis.
        console = _Console()
        console.states = [{"state": "expired"}]
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_agent_unavailable"):
                await client.find_user_dn("g")
        finally:
            await client.aclose()

    async def test_waiting_forever_ends_in_a_timeout(self) -> None:
        console = _Console()
        console.states = []  # bleibt "queued"
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_timeout"):
                await client.find_user_dn("g")
        finally:
            await client.aclose()

    async def test_a_broken_poll_is_an_ad_outage(self) -> None:
        console = _Console()
        console.poll_status = 500
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_poll_failed"):
                await client.find_user_dn("g")
        finally:
            await client.aclose()

    async def test_an_enqueue_without_an_id_is_refused(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={})

        client = _Console().client(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(AdUnavailableError, match="connector_enqueue_failed"):
                await client.find_user_dn("g")
        finally:
            await client.aclose()


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
class TestConsoleUrlDerivation:
    """Synchron — das Modul-``pytestmark`` gilt hier nicht."""

    def test_the_console_base_comes_from_the_registry_url(self) -> None:
        """Eine Einstellung weniger, die auseinanderlaufen kann."""
        from magister_api.ad.factory import console_base

        assert (
            console_base("https://console.magister.ch:4444/api/tenants/registry")
            == "https://console.magister.ch:4444"
        )
        assert (
            console_base("https://console.magister.ch:4444/") == "https://console.magister.ch:4444"
        )


class TestTheSyncRunsOverTheAgent:
    """Der Abgleich über den Connector (ADR-0022 D1).

    Ohne diese Überschreibung erbte der Rücken den direkten Körper und die
    Plattform griffe beim Abgleich per LDAP ins Kundennetz — die eine
    Verbindung, die es nach ADR-0014 nicht geben darf. Der Fehler wäre nicht
    aufgefallen: er sieht aus wie ein unerreichbarer Domänencontroller.
    """

    def _record_json(self, guid: str = "22222222-2222-2222-2222-222222222222") -> dict[str, Any]:
        """Ein Datensatz, wie der Agent ihn schickt.

        Gebaut aus dem **echten** Datensatz über denselben Kodierer, den der
        Agent benutzt — von Hand geschriebenes JSON wäre ein zweiter Stand des
        Formats und würde eine neue Spalte nicht bemerken.
        """
        return ad_user_record_to_jsonable(
            AdUserRecord(
                ad_object_guid=guid,
                upn="dora@example.ch",
                sam_account_name="dora",
                given_name="Dora",
                surname="D.",
                display_name="Dora D.",
                mail="dora@example.ch",
                enabled=True,
                kind="student",
                password_never_expires=False,
                ms_ds_consistency_guid=None,
                distinguished_name="CN=Dora,OU=Students,DC=schule,DC=local",
                street_address=None,
                locality=None,
                postal_code=None,
                country=None,
                when_changed=datetime(2026, 9, 11, 8, 0, tzinfo=UTC),
                groups=("CN=Schueler,DC=schule,DC=local",),
            )
        )

    async def test_records_come_back_as_records(self) -> None:
        console = _Console()
        console.states = [{"state": "done", "result": [self._record_json()]}]
        client = console.client()
        try:
            found = await client.search_users(search_base="DC=schule,DC=local")
        finally:
            await client.aclose()
        assert len(found) == 1
        # Kein JSON mehr, sondern das, womit die Fachschicht rechnet.
        assert found[0].upn == "dora@example.ch"
        assert found[0].when_changed is not None and found[0].when_changed.year == 2026
        assert found[0].groups == ("CN=Schueler,DC=schule,DC=local",)

    async def test_the_cursor_travels_as_iso_text(self) -> None:
        """JSON kennt keinen Zeitstempel; der Agent baut ihn zurück."""
        console = _Console()
        console.states = [{"state": "done", "result": []}]
        client = console.client()
        since = datetime(2026, 9, 10, 6, 30, tzinfo=UTC)
        try:
            await client.search_users(search_base="DC=schule,DC=local", changed_since=since)
        finally:
            await client.aclose()
        payload = console.enqueued[0]["payload"]
        assert console.enqueued[0]["method"] == "search_users"
        assert payload["changed_since"] == since.isoformat()
        assert payload["search_base"] == "DC=schule,DC=local"

    async def test_a_full_run_sends_no_cursor(self) -> None:
        console = _Console()
        console.states = [{"state": "done", "result": []}]
        client = console.client()
        try:
            await client.search_users(search_base="DC=schule,DC=local")
        finally:
            await client.aclose()
        assert console.enqueued[0]["payload"]["changed_since"] is None

    async def test_too_many_records_are_refused_not_truncated(self) -> None:
        """Ein halber Abgleich sieht aus wie ein ganzer — und ist schlimmer."""
        console = _Console()
        console.states = [
            {"state": "done", "result": [self._record_json()] * (MAX_SEARCH_RECORDS + 1)}
        ]
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_search_too_large"):
                await client.search_users(search_base="DC=schule,DC=local")
        finally:
            await client.aclose()

    async def test_a_strange_answer_is_an_outage_not_a_crash(self) -> None:
        console = _Console()
        console.states = [{"state": "done", "result": [{"upn": "nur ein feld"}]}]
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_search_malformed"):
                await client.search_users(search_base="DC=schule,DC=local")
        finally:
            await client.aclose()

    async def test_a_non_list_answer_is_an_outage(self) -> None:
        console = _Console()
        console.states = [{"state": "done", "result": "ups"}]
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="connector_search_malformed"):
                await client.search_users(search_base="DC=schule,DC=local")
        finally:
            await client.aclose()

    async def test_without_a_search_base_nothing_is_enqueued(self) -> None:
        """Dieselbe Ausnahme wie beim direkten Rücken, und ohne Auftrag."""
        console = _Console()
        client = console.client()
        try:
            with pytest.raises(AdUnavailableError, match="SEARCH_BASE"):
                await client.search_users()
        finally:
            await client.aclose()
        assert console.enqueued == []

    @pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
    def test_the_sync_waits_longer_than_a_person_would(self) -> None:
        """Die Frist des Abgleichs ist nicht die eines Formulars."""
        client = _Console().client(timeout_s=60.0)
        assert client._timeout_for("search_users") == SEARCH_TIMEOUT_S
        assert client._timeout_for("find_user_dn") == 60.0
        # Und sie bleibt unter der Frist, die die Konsole dem Auftrag gibt
        # (dort 10 Minuten) — sonst wartet die Datenebene auf etwas, das
        # schon verfallen ist.
        assert SEARCH_TIMEOUT_S < 600.0
