"""require_role dependency behaviour."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin, require_role, require_schulleitung


def _user(*, is_admin: bool = False, roles: tuple[str, ...] = ()) -> AuthenticatedUser:
    return AuthenticatedUser(
        ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
        upn="user@x.ch",
        is_admin=is_admin,
        school_scope=(),
        roles=roles,
        expires_at=datetime.now(UTC),
    )


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_admin_passes_any_role(self) -> None:
        dep = require_role("schulleitung")
        out = await dep(_user(is_admin=True))
        assert out.is_admin is True

    @pytest.mark.asyncio
    async def test_user_with_role_passes(self) -> None:
        dep = require_role("schulleitung")
        out = await dep(_user(roles=("schulleitung",)))
        assert "schulleitung" in out.roles

    @pytest.mark.asyncio
    async def test_user_without_role_403(self) -> None:
        dep = require_role("schulleitung")
        with pytest.raises(HTTPException) as exc:
            await dep(_user(roles=()))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_admin_blocks_schulleitung(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await require_admin(_user(roles=("schulleitung",)))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_schulleitung_passes_for_admin(self) -> None:
        out = await require_schulleitung(_user(is_admin=True))
        assert out.is_admin is True

    def test_require_role_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            require_role()
