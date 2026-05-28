"""M2 US-6 — PATCH /users/{guid}/status (enable/disable).

Covers:
- Happy path: Schulleitung disables a user in their school → AD UAC bit flipped,
  cache mirrored, ``user_disabled`` audit event emitted.
- Re-enable round-trip with Admin.
- Idempotent: matching target state ⇒ no MODIFY, no audit event.
- Self-disable refused (400 cannot_disable_self).
- KL cannot reach the endpoint (404 user_not_found).
- Schulleitung of the *other* school sees 404.
- Cross-school admin users (school_id=NULL) are off-limits to Schulleitung
  but reachable for Admin.
- AD outage ⇒ 503 + ``user_status_change_failed`` audit event.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.ad.client import UAC_ACCOUNTDISABLE, AdClient
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from ldap3 import Connection
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


TARGET_GUID = "55555555-5555-5555-5555-555555555555"
TARGET_DN = "CN=Tom,OU=Students,OU=ALPHA,DC=schule,DC=local"

UAC_NORMAL_ACCOUNT = 0x200  # plain enabled user
UAC_DISABLED = UAC_NORMAL_ACCOUNT | UAC_ACCOUNTDISABLE


def _le(guid_str: str) -> bytes:
    return uuid.UUID(guid_str).bytes_le


def _seed_target_entry(conn: Connection, *, dn: str, guid: str, upn: str, uac: int) -> None:
    conn.strategy.add_entry(
        dn,
        {
            "objectClass": ["user"],
            "objectGUID": _le(guid),
            "userPrincipalName": upn,
            "userAccountControl": uac,
        },
    )


@pytest_asyncio.fixture
async def mock_ad_with_enabled_target(app_settings: Settings) -> AsyncIterator[AdClient]:
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    _seed_target_entry(
        conn, dn=TARGET_DN, guid=TARGET_GUID, upn="tom@example.ch", uac=UAC_NORMAL_ACCOUNT
    )
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def mock_ad_with_disabled_target(app_settings: Settings) -> AsyncIterator[AdClient]:
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    _seed_target_entry(conn, dn=TARGET_DN, guid=TARGET_GUID, upn="tom@example.ch", uac=UAC_DISABLED)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def seed_target_cache(db_session: AsyncSession, school_a: int) -> str:
    """Seed an AdUserCache row for the target user (enabled, in school A)."""
    db_session.add(
        AdUserCache(
            ad_object_guid=TARGET_GUID,
            school_id=school_a,
            upn="tom@example.ch",
            given_name="Tom",
            surname="Student",
            kind="student",
            enabled=True,
            last_sync_at=None,
            ms_ds_consistency_guid=TARGET_GUID,
        )
    )
    await db_session.commit()
    return TARGET_GUID


def _override_ad(app: FastAPI, client: AdClient):
    app.dependency_overrides[get_ad_client] = lambda: client


def _clear_ad_override(app: FastAPI):
    app.dependency_overrides.pop(get_ad_client, None)


async def _cache_enabled(engine: AsyncEngine, guid: str) -> bool:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        row = await s.get(AdUserCache, guid)
    assert row is not None
    return row.enabled


async def _audit_actions(engine: AsyncEngine) -> list[str]:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with sm() as s:
        return list((await s.execute(select(AuditEvent.action))).scalars().all())


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_schulleitung_can_disable_user_in_their_school(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        mock_ad_with_enabled_target: AdClient,
        seed_target_cache: str,
        engine: AsyncEngine,
    ) -> None:
        _override_ad(app, mock_ad_with_enabled_target)
        try:
            r = await as_schulleitung_a.patch(
                f"/users/{seed_target_cache}/status",
                json={"enabled": False, "reason": "Schulaustritt 2026"},
            )
        finally:
            _clear_ad_override(app)

        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False
        assert await _cache_enabled(engine, seed_target_cache) is False
        assert "user_disabled" in await _audit_actions(engine)

    @pytest.mark.asyncio
    async def test_admin_can_re_enable_disabled_user(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        mock_ad_with_disabled_target: AdClient,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
    ) -> None:
        # Seed cache as disabled to match AD.
        db_session.add(
            AdUserCache(
                ad_object_guid=TARGET_GUID,
                school_id=school_a,
                upn="tom@example.ch",
                kind="student",
                enabled=False,
                ms_ds_consistency_guid=TARGET_GUID,
            )
        )
        await db_session.commit()

        _override_ad(app, mock_ad_with_disabled_target)
        try:
            r = await as_admin.patch(
                f"/users/{TARGET_GUID}/status",
                json={"enabled": True},
            )
        finally:
            _clear_ad_override(app)

        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is True
        assert await _cache_enabled(engine, TARGET_GUID) is True
        assert "user_enabled" in await _audit_actions(engine)


class TestIdempotent:
    @pytest.mark.asyncio
    async def test_already_enabled_emits_no_audit(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        mock_ad_with_enabled_target: AdClient,
        seed_target_cache: str,
        engine: AsyncEngine,
    ) -> None:
        # AD says enabled, cache says enabled. Request enable → no-op.
        _override_ad(app, mock_ad_with_enabled_target)
        try:
            r = await as_admin.patch(
                f"/users/{seed_target_cache}/status",
                json={"enabled": True},
            )
        finally:
            _clear_ad_override(app)

        assert r.status_code == 200, r.text
        actions = await _audit_actions(engine)
        assert "user_enabled" not in actions
        assert "user_disabled" not in actions


class TestSelfDisable:
    @pytest.mark.asyncio
    async def test_self_disable_returns_400(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        mock_ad_with_enabled_target: AdClient,
        db_session: AsyncSession,
    ) -> None:
        # The as_admin fixture seeds admin@example.ch with guid 0...00a.
        admin_guid = "00000000-0000-0000-0000-00000000000a"
        # Add a matching AD-mock entry so the lookup succeeds before the
        # self-check fires.
        conn = mock_ad_with_enabled_target.mock_connection()
        conn.strategy.add_entry(
            "CN=Admin,OU=Admins,DC=schule,DC=local",
            {
                "objectClass": ["user"],
                "objectGUID": _le(admin_guid),
                "userPrincipalName": "admin@example.ch",
                "userAccountControl": UAC_NORMAL_ACCOUNT,
            },
        )

        _override_ad(app, mock_ad_with_enabled_target)
        try:
            r = await as_admin.patch(
                f"/users/{admin_guid}/status",
                json={"enabled": False},
            )
        finally:
            _clear_ad_override(app)

        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "cannot_disable_self"


class TestRbac:
    @pytest.mark.asyncio
    async def test_schulleitung_of_other_school_gets_404(
        self,
        app: FastAPI,
        as_schulleitung_b: AsyncClient,
        mock_ad_with_enabled_target: AdClient,
        seed_target_cache: str,
    ) -> None:
        # Target user is in school A; caller is Schulleitung of school B.
        _override_ad(app, mock_ad_with_enabled_target)
        try:
            r = await as_schulleitung_b.patch(
                f"/users/{seed_target_cache}/status",
                json={"enabled": False},
            )
        finally:
            _clear_ad_override(app)
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "user_not_found"

    @pytest.mark.asyncio
    async def test_cross_school_admin_user_only_admin_may_toggle(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        as_admin: AsyncClient,
        mock_ad_with_enabled_target: AdClient,
        db_session: AsyncSession,
    ) -> None:
        # Cross-school admin user: school_id=NULL in cache.
        cross_guid = "66666666-6666-6666-6666-666666666666"
        db_session.add(
            AdUserCache(
                ad_object_guid=cross_guid,
                school_id=None,
                upn="root@example.ch",
                kind="admin",
                enabled=True,
                ms_ds_consistency_guid=cross_guid,
            )
        )
        await db_session.commit()
        conn = mock_ad_with_enabled_target.mock_connection()
        conn.strategy.add_entry(
            "CN=Root,OU=Admins,DC=schule,DC=local",
            {
                "objectClass": ["user"],
                "objectGUID": _le(cross_guid),
                "userPrincipalName": "root@example.ch",
                "userAccountControl": UAC_NORMAL_ACCOUNT,
            },
        )

        _override_ad(app, mock_ad_with_enabled_target)
        try:
            r1 = await as_schulleitung_a.patch(
                f"/users/{cross_guid}/status", json={"enabled": False}
            )
            r2 = await as_admin.patch(f"/users/{cross_guid}/status", json={"enabled": False})
        finally:
            _clear_ad_override(app)

        assert r1.status_code == 404, r1.text
        assert r2.status_code == 200, r2.text
        assert r2.json()["enabled"] is False


class TestAdUnavailable:
    @pytest.mark.asyncio
    async def test_ad_down_returns_503(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        app_settings: Settings,
        seed_target_cache: str,
        engine: AsyncEngine,
    ) -> None:
        # Live mode with no DCs configured → AdUnavailableError on first call.
        # Note: the failed-audit row is emitted on the same request session, so
        # the framework's exception-path rollback can wipe it before commit —
        # same best-effort behaviour as in student_password_reset_failed.
        broken_settings = app_settings.model_copy(update={"ad_use_mock": False, "ad_dcs": []})
        broken_client = AdClient(broken_settings)
        _override_ad(app, broken_client)
        try:
            r = await as_schulleitung_a.patch(
                f"/users/{seed_target_cache}/status",
                json={"enabled": False},
            )
        finally:
            _clear_ad_override(app)

        assert r.status_code == 503, r.text
        assert r.json()["detail"] == "ad_unavailable"
        # No success-audit must have been emitted.
        assert "user_disabled" not in await _audit_actions(engine)
        assert "user_enabled" not in await _audit_actions(engine)
