"""Shared fixtures.

Since ADR-0015 D1 the console refuses anything that did not come through the
management listener, so the default test client speaks through it — otherwise
every test would only ever see the guard's 404. The guard itself is tested
explicitly in ``test_management_guard.py``.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.main import app
from cockpit_api.management_guard import CONNECTOR_MARKER_HEADER, MARKER_HEADER
from cockpit_api.models import Base

TEST_MARKER = "test-management-marker"
TEST_CONNECTOR_MARKER = "test-connector-marker"


@pytest.fixture(autouse=True)
def _management_config() -> Iterator[None]:
    """Configure a marker so the app starts and the guard is exercisable."""
    previous = (
        settings.require_management_listener,
        settings.management_marker,
        settings.published_address,
    )
    settings.require_management_listener = True
    settings.management_marker = TEST_MARKER
    settings.published_address = "10.0.0.5:4444"
    previous_connector = settings.connector_marker
    settings.connector_marker = TEST_CONNECTOR_MARKER
    yield
    settings.connector_marker = previous_connector
    (
        settings.require_management_listener,
        settings.management_marker,
        settings.published_address,
    ) = previous


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client that arrives through the management listener, like Caddy does."""
    with TestClient(app, headers={MARKER_HEADER: TEST_MARKER}) as c:
        yield c


@pytest.fixture
def public_client() -> Iterator[TestClient]:
    """A client that does NOT — i.e. someone probing the public origin."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client() -> Iterator[TestClient]:
    """Through the listener AND authenticated with the break-glass token.

    ``client`` stays unauthenticated on purpose: two tests assert that the
    routers refuse without a token, and that assertion is worth keeping.
    """
    headers = {
        MARKER_HEADER: TEST_MARKER,
        "Authorization": f"Bearer {settings.bootstrap_token}",
    }
    with TestClient(app, headers=headers) as c:
        yield c


# --- Datenbankgestützte Tests (Bereitstellung, ADR-0013 D2) ----------------
# Übersprungen, wenn keine Testdatenbank konfiguriert ist: die reinen
# Logiktests sollen ohne Postgres laufen.


def _cockpit_url() -> str | None:
    return os.environ.get("COCKPIT_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def cockpit_database_url() -> str:
    url = _cockpit_url()
    if not url:
        pytest.skip("COCKPIT_TEST_DATABASE_URL nicht gesetzt")
    return url


@pytest.fixture(scope="session")
def magister_admin_dsn() -> str:
    """Verwaltungszugang in den Magister-Cluster (CREATEROLE, CREATE)."""
    url = os.environ.get("COCKPIT_TEST_TENANT_ADMIN_DSN")
    if not url:
        pytest.skip("COCKPIT_TEST_TENANT_ADMIN_DSN nicht gesetzt")
    return url


@pytest.fixture
def cockpit_schema(cockpit_database_url: str) -> str:
    """Konsolen-Schema über **Alembic** neu aufbauen.

    Nicht ``Base.metadata.create_all``. Der Unterschied ist nicht Geschmack:
    ``create_all`` erzeugt das Schema aus denselben Modell-Annahmen, mit denen
    die Anwendung schreibt. Ein Fehler in einer Annahme baut sich damit das
    passende Schema selbst und fällt nie auf.

    Genau so passiert: ``IsolationMode.schema_only = "schema"`` — SQLAlchemy
    speichert standardmässig den *Namen*, die Migration legte den *Wert* an.
    Alle Tests waren grün, und die erste Kunden-Anlage gegen die echte
    Datenbank endete im 500er. Seit diesem Fund läuft hier dasselbe Alembic
    wie in Produktion.

    Bewusst eine **synchrone** Fixture: ``TestClient`` fährt die Anwendung in
    einer eigenen Ereignisschleife, und eine Engine aus der Fixture-Schleife
    bringt ihre Verbindungen dorthin mit ("attached to a different loop").
    Alembic bekommt deshalb einen eigenen Prozess.
    """

    async def drop_everything() -> None:
        engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                # Enum-Typen überleben drop_all nicht immer; Alembic würde
                # sonst über einen bestehenden Typ stolpern.
                await conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
                for enum_name in (
                    "offboarding_state",
                    "export_state",
                    "restore_state",
                    "backup_status",
                    "backup_kind",
                    "connector_job_state",
                    "connector_agent_status",
                    "provisioning_step",
                    "provisioning_job_status",
                    "tenant_isolation_mode",
                    "tenant_profile",
                    "tenant_status",
                    "update_request_status",
                    "instance_channel",
                ):
                    await conn.exec_driver_sql(f"DROP TYPE IF EXISTS {enum_name}")
        finally:
            await engine.dispose()

    asyncio.run(drop_everything())
    env = dict(os.environ)
    env["COCKPIT_DATABASE_URL"] = cockpit_database_url
    # Feste Argumentliste, keine Shell.
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        pytest.fail(f"alembic upgrade head fehlgeschlagen: {tail[-1] if tail else '?'}")
    return cockpit_database_url


@pytest.fixture
def console_client(cockpit_schema: str) -> Iterator[TestClient]:
    """Client mit echter Konsolen-Datenbank — **ohne** Magister-Cluster.

    Für alles, was nur die Konsolen-Datenbank braucht (Einstellungen,
    Soll-Zustand). ``db_client`` verlangt zusätzlich einen zweiten Cluster für
    die Bereitstellung; ein Test über Einstellungen wäre damit übersprungen,
    sobald der nicht da ist — und würde still nichts prüfen.
    """

    async def _override() -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(cockpit_schema, poolclass=NullPool)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sm() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_session] = _override
    headers = {
        MARKER_HEADER: TEST_MARKER,
        "Authorization": f"Bearer {settings.bootstrap_token}",
    }
    try:
        with TestClient(app, headers=headers) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def db_client(cockpit_schema: str, magister_admin_dsn: str) -> Iterator[TestClient]:
    """Client mit echter Konsolen-Datenbank und echtem Magister-Cluster."""

    async def _override() -> AsyncIterator[AsyncSession]:
        # Engine pro Anfrage, NullPool: entsteht in der Schleife, in der sie
        # auch benutzt wird. Für Tests ist das billig und korrekt.
        engine = create_async_engine(cockpit_schema, poolclass=NullPool)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sm() as session:
                yield session
        finally:
            await engine.dispose()

    previous = (
        settings.tenant_admin_dsn,
        settings.magister_api_dir,
        settings.expected_schema_version,
    )
    settings.tenant_admin_dsn = magister_admin_dsn
    settings.magister_api_dir = os.environ.get("COCKPIT_TEST_MAGISTER_API_DIR", "")
    settings.expected_schema_version = os.environ.get("COCKPIT_TEST_SCHEMA_VERSION", "")
    app.dependency_overrides[get_session] = _override
    headers = {
        MARKER_HEADER: TEST_MARKER,
        "Authorization": f"Bearer {settings.bootstrap_token}",
    }
    try:
        with TestClient(app, headers=headers) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        (
            settings.tenant_admin_dsn,
            settings.magister_api_dir,
            settings.expected_schema_version,
        ) = previous


@pytest.fixture
def agent_headers() -> dict[str, str]:
    """Header, die der Connector-Listener setzt (TCP 46200, ADR-0014).

    Bewusst NICHT der Management-Marker: die beiden Listener sind getrennt,
    und ein Test, der das verwischt, würde die Trennung nicht mehr prüfen.
    """
    return {CONNECTOR_MARKER_HEADER: TEST_CONNECTOR_MARKER}
