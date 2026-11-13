"""Bootstrap-admin flow against a real DB (ADR-0025).

``bootstrap_admins`` are Keycloak user names. The grant lands on the login
account's ``principal_guid``; no ``oid`` and no ``ad_user_cache`` row needed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.bootstrap import is_bootstrap_admin, maybe_bootstrap_admin
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, RoleAssignment

pytestmark = pytest.mark.postgres


def _settings_with_admins(*names: str) -> Settings:
    return Settings(
        audit_key="x",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
        bootstrap_admins=list(names),
    )


async def _roles(db_session: AsyncSession, guid: str) -> list[RoleAssignment]:
    stmt = select(RoleAssignment).where(RoleAssignment.ad_object_guid == guid)
    return list((await db_session.execute(stmt)).scalars().all())


class TestBootstrap:
    @pytest.mark.asyncio
    async def test_first_login_grants_admin(self, db_session: AsyncSession) -> None:
        s = _settings_with_admins("automato-admin")
        guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        result = await maybe_bootstrap_admin(
            session=db_session, settings=s, username="automato-admin", principal_guid=guid
        )
        await db_session.flush()
        assert result.granted is True
        assert result.already_admin is False

        # Keine Zeile im AD-Abbild: der Benutzer steht nur in Keycloak.
        assert await db_session.get(AdUserCache, guid) is None

        roles = await _roles(db_session, guid)
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
                session=db_session, settings=s, username="admin@example.ch", principal_guid=guid
            )
            await db_session.flush()
        assert len(await _roles(db_session, guid)) == 1

    @pytest.mark.asyncio
    async def test_non_listed_name_no_grant(self, db_session: AsyncSession) -> None:
        s = _settings_with_admins("automato-admin")
        guid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        result = await maybe_bootstrap_admin(
            session=db_session, settings=s, username="random.teacher", principal_guid=guid
        )
        await db_session.flush()
        assert result.granted is False
        assert result.already_admin is False
        assert await _roles(db_session, guid) == []


def test_names_compare_case_and_space_insensitive() -> None:
    s = _settings_with_admins(" Automato-Admin ", "")
    assert is_bootstrap_admin(s, "automato-admin")
    assert is_bootstrap_admin(s, "AUTOMATO-ADMIN")
    assert not is_bootstrap_admin(s, "")
    assert not is_bootstrap_admin(s, "automato")
