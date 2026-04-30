"""Bootstrap-admin flow against a real DB.

DoD for issue #1: env-var → first login → admin role granted, idempotent.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.bootstrap import maybe_bootstrap_admin
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, RoleAssignment

pytestmark = pytest.mark.postgres


def _settings_with_admins(*upns: str) -> Settings:
    return Settings(
        audit_key="x",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
        bootstrap_admins=list(upns),
    )


class TestBootstrap:
    @pytest.mark.asyncio
    async def test_first_login_grants_admin(self, db_session: AsyncSession) -> None:
        s = _settings_with_admins("admin@example.ch")
        result = await maybe_bootstrap_admin(
            session=db_session,
            settings=s,
            upn="admin@example.ch",
            ad_object_guid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            oidc_oid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        await db_session.flush()
        assert result.granted is True
        assert result.already_admin is False

        cached = await db_session.get(AdUserCache, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        assert cached is not None
        assert cached.kind == "admin"
        assert cached.school_id is None

        roles = (
            (
                await db_session.execute(
                    select(RoleAssignment).where(
                        RoleAssignment.ad_object_guid == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(roles) == 1
        assert roles[0].role == "admin"
        assert roles[0].school_id is None
        assert roles[0].granted_by == "bootstrap"

    @pytest.mark.asyncio
    async def test_idempotent(self, db_session: AsyncSession) -> None:
        s = _settings_with_admins("admin@example.ch")
        guid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        for _ in range(3):
            await maybe_bootstrap_admin(
                session=db_session,
                settings=s,
                upn="admin@example.ch",
                ad_object_guid=guid,
                oidc_oid=guid,
            )
            await db_session.flush()
        roles = (
            (
                await db_session.execute(
                    select(RoleAssignment).where(RoleAssignment.ad_object_guid == guid)
                )
            )
            .scalars()
            .all()
        )
        assert len(roles) == 1

    @pytest.mark.asyncio
    async def test_non_listed_upn_no_grant(self, db_session: AsyncSession) -> None:
        s = _settings_with_admins("admin@example.ch")
        result = await maybe_bootstrap_admin(
            session=db_session,
            settings=s,
            upn="random.teacher@example.ch",
            ad_object_guid="cccccccc-cccc-cccc-cccc-cccccccccccc",
            oidc_oid=None,
        )
        await db_session.flush()
        assert result.granted is False
        assert result.already_admin is False
        cached = await db_session.get(AdUserCache, "cccccccc-cccc-cccc-cccc-cccccccccccc")
        assert cached is None
