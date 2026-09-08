"""Shared fixtures.

Since ADR-0015 D1 the console refuses anything that did not come through the
management listener, so the default test client speaks through it — otherwise
every test would only ever see the guard's 404. The guard itself is tested
explicitly in ``test_management_guard.py``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

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
from cockpit_api.management_guard import MARKER_HEADER
from cockpit_api.models import Base

TEST_MARKER = "test-management-marker"


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
    yield
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
    """Konsolen-Schema neu aufbauen.

    Bewusst eine **synchrone** Fixture mit ``asyncio.run`` und ``NullPool``:
    ``TestClient`` fährt die Anwendung in einer eigenen Ereignisschleife. Eine
    Engine, die in der Schleife der Fixture entstanden ist, bringt ihre
    Verbindungen dorthin mit und scheitert dann mit „attached to a different
    loop". Jede Engine wird deshalb in der Schleife gebaut, die sie benutzt.
    """

    async def rebuild() -> None:
        engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(rebuild())
    return cockpit_database_url


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
