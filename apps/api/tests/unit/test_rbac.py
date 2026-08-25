"""require_role dependency behaviour."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from magister_api.auth.capabilities import ROLE_CAPABILITIES, RbacMatrix
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import (
    require_admin,
    require_role,
    require_schulleitung,
    require_smi,
)

# Default matrix (ADR-0010) — the capability gates load it per request in prod;
# here we pass it directly since these unit calls bypass FastAPI DI.
_MATRIX = RbacMatrix(role_caps=dict(ROLE_CAPABILITIES), admin_roles=frozenset({"admin"}))


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
            await require_admin(_user(roles=("schulleitung",)), _MATRIX)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_schulleitung_passes_for_admin(self) -> None:
        out = await require_schulleitung(_user(is_admin=True), _MATRIX)
        assert out.is_admin is True

    def test_require_role_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            require_role()

    @pytest.mark.asyncio
    async def test_require_smi_passes_for_smi_role(self) -> None:
        out = await require_smi(_user(roles=("smi",)), _MATRIX)
        assert "smi" in out.roles

    @pytest.mark.asyncio
    async def test_require_smi_passes_for_admin(self) -> None:
        out = await require_smi(_user(is_admin=True), _MATRIX)
        assert out.is_admin is True

    @pytest.mark.asyncio
    async def test_require_smi_blocks_schulleitung(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await require_smi(_user(roles=("schulleitung",)), _MATRIX)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_smi_passes_user_listing(self) -> None:
        """``/users`` accepts schulleitung OR smi (plus admin)."""
        dep = require_role("schulleitung", "smi")
        out = await dep(_user(roles=("smi",)))
        assert "smi" in out.roles

    @pytest.mark.asyncio
    async def test_kl_only_blocked_from_user_listing(self) -> None:
        dep = require_role("schulleitung", "smi")
        with pytest.raises(HTTPException) as exc:
            await dep(_user(roles=("kl",)))
        assert exc.value.status_code == 403
