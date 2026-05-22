"""Integration-test conftest.

- Session-scoped: engine, app, settings (schema created once)
- Function-scoped: client, db_session, autouse `_truncate_tables`
- Per-test fixtures `as_admin` / `as_schulleitung_a` create authenticated clients
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.main import create_app
from magister_api.models import Base
from magister_api.models.school import School
from tests.integration._helpers import seed_user_with_session


def _url() -> str | None:
    return os.environ.get("MAGISTER_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _url()
    if not url:
        pytest.skip("MAGISTER_TEST_DATABASE_URL not set")
    return url


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url, future=True, pool_pre_ping=True)
    async with eng.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Mirror partial unique indexes that Alembic creates.
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_role_assignments_admin_unique "
            "ON role_assignments (ad_object_guid, role) "
            "WHERE school_id IS NULL AND revoked_at IS NULL"
        )
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_classes_school_active_name "
            "ON classes (school_id, name) WHERE status = 'active'"
        )
        # The 0006 migration inserts the singleton; mirror that for tests
        # that bypass alembic and use Base.metadata.create_all.
        await conn.exec_driver_sql(
            "INSERT INTO app_settings (id, version, oidc_scopes, "
            "bootstrap_admins, ad_dcs) "
            "VALUES (1, 1, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb) "
            "ON CONFLICT DO NOTHING"
        )
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def app_settings(database_url: str) -> Settings:
    return Settings(
        environment="test",  # type: ignore[arg-type]
        database_url=database_url,
        audit_key="integration-audit-key",  # type: ignore[arg-type]
        session_secret="integration-session-secret",  # type: ignore[arg-type]
        csrf_secret="integration-csrf-secret",  # type: ignore[arg-type]
        oidc_issuer="https://login.example.test/v2.0",
        oidc_client_id="client-id",
        oidc_client_secret="client-secret",  # type: ignore[arg-type]
        oidc_redirect_uri="http://testserver/auth/callback",
        bootstrap_admins=["admin@example.ch"],
        session_cookie_secure=False,
    )


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, app_settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(app_settings)
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with sm() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    application.dependency_overrides[get_settings] = lambda: app_settings
    application.dependency_overrides[get_session] = _override_session
    yield application


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Wipe all tables between tests so they stay independent."""
    yield
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE class_memberships, class_teacher_roles, classes, audit_events, "
            "sessions, role_assignments, ad_user_cache, schools, local_admins, "
            "app_settings RESTART IDENTITY CASCADE"
        )
        # The migration inserts the singleton; recreate it after each
        # truncate so reads keep returning a row.
        await conn.exec_driver_sql(
            "INSERT INTO app_settings (id, version, oidc_scopes, "
            "bootstrap_admins, ad_dcs) "
            "VALUES (1, 1, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb) "
            "ON CONFLICT DO NOTHING"
        )


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """slowapi keeps an in-memory store across tests in the same process.

    Without this reset, rate-limited routes (``/auth/login/local``,
    ``/students/.../password-reset``) bleed counts into each other and
    legitimate requests start returning 429.
    """
    from magister_api.routers.auth import limiter

    limiter.reset()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Read-/write-DB session for tests that talk to the DB directly (not via HTTP)."""
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# --- Authenticated-client fixtures ----------------------------------------------------


def _build_client_with_session(app: FastAPI, sid: str, csrf: str) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"magister_session": sid, "magister_csrf": csrf},
        headers={"X-CSRF-Token": csrf},
    )


@pytest_asyncio.fixture
async def school_a(db_session: AsyncSession) -> int:
    s = School(name="Schule A", kuerzel="A", scope_short="A")
    db_session.add(s)
    await db_session.flush()
    await db_session.commit()
    return s.id


@pytest_asyncio.fixture
async def school_b(db_session: AsyncSession) -> int:
    s = School(name="Schule B", kuerzel="B", scope_short="B")
    db_session.add(s)
    await db_session.flush()
    await db_session.commit()
    return s.id


@pytest_asyncio.fixture
async def as_admin(
    app: FastAPI, app_settings: Settings, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn="admin@example.ch",
        ad_object_guid="00000000-0000-0000-0000-00000000000a",
        school_id=None,
        kind="admin",
        role="admin",
        role_school_id=None,
    )
    await db_session.commit()
    async with _build_client_with_session(app, sid, csrf) as c:
        yield c


@pytest_asyncio.fixture
async def as_schulleitung_a(
    app: FastAPI,
    app_settings: Settings,
    db_session: AsyncSession,
    school_a: int,
) -> AsyncIterator[AsyncClient]:
    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn="sl-a@example.ch",
        ad_object_guid="00000000-0000-0000-0000-0000000000a1",
        school_id=school_a,
        kind="teacher",
        role="schulleitung",
        role_school_id=school_a,
    )
    await db_session.commit()
    async with _build_client_with_session(app, sid, csrf) as c:
        yield c


@pytest_asyncio.fixture
async def as_schulleitung_b(
    app: FastAPI,
    app_settings: Settings,
    db_session: AsyncSession,
    school_b: int,
) -> AsyncIterator[AsyncClient]:
    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn="sl-b@example.ch",
        ad_object_guid="00000000-0000-0000-0000-0000000000b1",
        school_id=school_b,
        kind="teacher",
        role="schulleitung",
        role_school_id=school_b,
    )
    await db_session.commit()
    async with _build_client_with_session(app, sid, csrf) as c:
        yield c


@pytest_asyncio.fixture
async def as_smi_a(
    app: FastAPI,
    app_settings: Settings,
    db_session: AsyncSession,
    school_a: int,
) -> AsyncIterator[AsyncClient]:
    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=app_settings,
        upn="smi-a@example.ch",
        ad_object_guid="00000000-0000-0000-0000-0000000000a2",
        school_id=school_a,
        kind="teacher",
        role="smi",
        role_school_id=school_a,
    )
    await db_session.commit()
    async with _build_client_with_session(app, sid, csrf) as c:
        yield c


# Re-export for tests that need raw access.
__all__ = ["seed_user_with_session"]
_ = (Any,)
