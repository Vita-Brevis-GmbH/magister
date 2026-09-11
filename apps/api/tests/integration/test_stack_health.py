"""Die tiefe Sonde je Kundenseite — und der Token davor.

Was diese Datei festhält, ist nicht „gibt 200 zurück", sondern die vier Fälle,
in denen der Anfragepfad schweigt: Schemastand zurück, Kundenschlüssel fehlt,
Kunde gesperrt, Datenbank weg. Genau dann antwortet die Kundenseite mit
`503 maintenance` und sagt **nicht**, warum — sonst wäre die Begründung eine
Auskunft an jeden Besucher.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette

from magister_api.config import Settings
from magister_api.main import create_app
from magister_api.services.stack_health import CRITICAL, OK, WARNING, stack_health
from magister_api.tenancy.registry import Tenant, TenantRegistry, TenantStatus
from magister_api.tenancy.version import HEAD_REVISION

pytestmark = pytest.mark.postgres

HOST = "thun.mgmt.example.ch"


def _tenant(database_url: str, **over: object) -> Tenant:
    base: dict[str, object] = {
        "slug": "thun",
        "name": "Thun",
        "dsn": database_url,
        "schema_name": "public",
        "db_role": None,
        "schema_version": "",
        "status": TenantStatus.ACTIVE,
        "hostname": HOST,
    }
    base.update(over)
    return Tenant(**base)  # type: ignore[arg-type]


@pytest.fixture
def sm(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class TestTheChecks:
    @pytest.mark.asyncio
    async def test_a_healthy_site_is_zero(
        self, app_settings: Settings, database_url: str, sm: async_sessionmaker[AsyncSession]
    ) -> None:
        tenant = _tenant(database_url)
        health = await stack_health(
            HOST,
            settings=app_settings,
            registry=TenantRegistry([tenant]),
            session_factory=lambda _t: sm,
        )
        assert health.tenant_slug == "thun"
        names = {c.name: c.status for c in health.checks}
        assert names["registry"] == OK
        assert names["tenant_status"] == OK
        assert names["schema_version"] == OK
        assert names["database"] == OK
        # Noch nie abgeglichen — das ist eine Warnung und keine Störung.
        assert names["ad_sync"] == WARNING
        assert health.status == WARNING

    @pytest.mark.asyncio
    async def test_an_unknown_hostname_is_critical(
        self, app_settings: Settings, database_url: str, sm: async_sessionmaker[AsyncSession]
    ) -> None:
        """Der häufigste Betriebsfehler: DNS zeigt hierher, die Registry kennt ihn nicht."""
        health = await stack_health(
            "fremd.example.ch",
            settings=app_settings,
            registry=TenantRegistry([_tenant(database_url)]),
            session_factory=lambda _t: sm,
        )
        assert health.status == CRITICAL
        assert health.tenant_slug is None
        assert [c.name for c in health.checks] == ["registry"]

    @pytest.mark.asyncio
    async def test_a_schema_behind_the_code_says_so(
        self, app_settings: Settings, database_url: str, sm: async_sessionmaker[AsyncSession]
    ) -> None:
        """Der Fall, für den es die Sonde gibt.

        Die Kundenseite antwortet hier mit `503 maintenance` und nennt keinen
        Grund. Ohne diese Route stünde in der Überwachung „Seite kaputt" und
        im Log eine Zeile, die jemand suchen müsste.
        """
        health = await stack_health(
            HOST,
            settings=app_settings,
            registry=TenantRegistry([_tenant(database_url, schema_version="0001_alt")]),
            session_factory=lambda _t: sm,
        )
        assert health.status == CRITICAL
        schema = next(c for c in health.checks if c.name == "schema_version")
        assert schema.status == CRITICAL
        assert "0001_alt" in schema.detail and HEAD_REVISION in schema.detail

    @pytest.mark.asyncio
    async def test_a_suspended_tenant_is_a_warning_not_a_fault(
        self, app_settings: Settings, database_url: str, sm: async_sessionmaker[AsyncSession]
    ) -> None:
        health = await stack_health(
            HOST,
            settings=app_settings,
            registry=TenantRegistry([_tenant(database_url, status=TenantStatus.SUSPENDED)]),
            session_factory=lambda _t: sm,
        )
        status = next(c for c in health.checks if c.name == "tenant_status")
        assert status.status == WARNING
        assert "Entscheidung" in status.detail

    @pytest.mark.asyncio
    async def test_a_missing_tenant_key_stops_before_the_database(
        self, app_settings: Settings, database_url: str, sm: async_sessionmaker[AsyncSession]
    ) -> None:
        """Ohne Schlüssel gibt es keine Sitzung — und keine zweite Fehlermeldung.

        Ab zwei Mandanten gelten die mandantenlosen Schlüssel nicht mehr
        (ADR-0016 D8). Fehlt der eigene, ist das der Grund; ein „Datenbank
        nicht erreichbar" daneben wäre die Folge und würde die Suche in die
        falsche Richtung schicken.
        """
        second = make_url(database_url).set(username="r_bern", password="egal")
        registry = TenantRegistry(
            [
                _tenant(
                    make_url(database_url)
                    .set(username="r_thun", password="egal")
                    .render_as_string(hide_password=False),
                    schema_name="t_thun",
                    db_role="r_thun",
                ),
                _tenant(
                    second.render_as_string(hide_password=False),
                    slug="bern",
                    name="Bern",
                    schema_name="t_bern",
                    db_role="r_bern",
                    hostname="bern.mgmt.example.ch",
                ),
            ]
        )
        health = await stack_health(
            HOST, settings=app_settings, registry=registry, session_factory=lambda _t: sm
        )
        assert health.status == CRITICAL
        assert [c.name for c in health.checks][-1] == "tenant_key"
        assert not any(c.name == "database" for c in health.checks)

    @pytest.mark.asyncio
    async def test_an_unreachable_database_does_not_raise(
        self, app_settings: Settings, database_url: str
    ) -> None:
        """Eine Sonde, die wirft, sagt nichts."""

        def _explode(_t: Tenant) -> async_sessionmaker[AsyncSession]:
            raise RuntimeError("keine Verbindung")

        health = await stack_health(
            HOST,
            settings=app_settings,
            registry=TenantRegistry([_tenant(database_url)]),
            session_factory=_explode,
        )
        assert health.status == CRITICAL
        db = next(c for c in health.checks if c.name == "database")
        assert "RuntimeError" in db.detail
        # Kein DSN in der Antwort: der Text käme aus dem Treiber.
        assert "postgresql" not in db.detail


# --- Die Route und der Token ------------------------------------------------------


@pytest.fixture
def app_settings(app_settings: Settings) -> Settings:
    """Dieselben Einstellungen wie sonst, plus ein Token für die Sonde."""
    return app_settings.model_copy(update={"health_token": SecretStr("probe-token")})


@pytest_asyncio.fixture
async def probe_client(app_settings: Settings) -> AsyncIterator[AsyncClient]:
    application: Starlette = create_app(app_settings)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestTheToken:
    @pytest.mark.asyncio
    async def test_without_a_token_the_route_does_not_exist(
        self, probe_client: AsyncClient
    ) -> None:
        resp = await probe_client.get("/healthz/stack")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_a_wrong_token_looks_the_same(self, probe_client: AsyncClient) -> None:
        """Wer rät, soll nicht erfahren, dass er nah dran war."""
        resp = await probe_client.get("/healthz/stack", headers={"X-Magister-Health": "falsch"})
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}

    @pytest.mark.asyncio
    async def test_the_header_opens_it(self, probe_client: AsyncClient) -> None:
        resp = await probe_client.get(
            "/healthz/stack", headers={"X-Magister-Health": "probe-token"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in (0, 1, 2)
        assert {c["name"] for c in body["checks"]} >= {"registry"}

    @pytest.mark.asyncio
    async def test_the_query_parameter_works_too(self, probe_client: AsyncClient) -> None:
        """PRTG kann nicht in jedem Sensortyp Kopfzeilen setzen.

        Der Kopf bleibt der richtige Weg — als Abfrageparameter steht der
        Token im Zugriffsprotokoll des Reverse-Proxy. Beides zu können ist
        eine Entscheidung für den Betrieb, keine Nachlässigkeit.
        """
        resp = await probe_client.get("/healthz/stack?token=probe-token")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_the_flat_probe_stays_open(self, probe_client: AsyncClient) -> None:
        # Sonst könnte der Container-Healthcheck seinen eigenen Dienst nicht
        # mehr prüfen.
        resp = await probe_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
