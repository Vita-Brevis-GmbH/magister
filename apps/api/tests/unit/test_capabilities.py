"""Capability-based RBAC (M6 Phase 3, ADR-0008).

The important test here is the *equivalence matrix*: it pins every ``require_*``
gate — including the ones migrated off bare ``require_role`` — to the exact set
of (admin/role) callers that passed before the capability refactor. If the
role→capability map ever drifts, one of these authorizations changes and the
matrix fails.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from magister_api.auth.capabilities import (
    Capability,
    effective_capabilities,
    has_capability,
    require_capability,
)
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import (
    require_admin,
    require_manage,
    require_schulleitung,
    require_smi,
)
from magister_api.routers.audit import require_audit_reader
from magister_api.routers.imports import _authorize_kind, require_import_access
from magister_api.routers.users import require_listing, require_user_edit_reader

_ADMIN = "admin"
_SL = "schulleitung"
_SMI = "smi"
_KL = "kl"


def _user(*, is_admin: bool = False, roles: tuple[str, ...] = ()) -> AuthenticatedUser:
    return AuthenticatedUser(
        ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
        upn="user@x.ch",
        is_admin=is_admin,
        school_scope=(),
        roles=roles,
        expires_at=datetime.now(UTC),
    )


# Each caller identity, keyed by a short label.
_CALLERS: dict[str, AuthenticatedUser] = {
    _ADMIN: _user(is_admin=True),
    _SL: _user(roles=(_SL,)),
    _SMI: _user(roles=(_SMI,)),
    _KL: _user(roles=(_KL,)),
    "none": _user(roles=()),
}

# Historical authorization per gate: which caller labels must PASS. This mirrors
# the pre-capability role gates exactly.
_GATE_MATRIX: dict[str, set[str]] = {
    "require_admin": {_ADMIN},
    "require_schulleitung": {_ADMIN, _SL},
    "require_smi": {_ADMIN, _SMI},
    "require_manage": {_ADMIN, _SL, _SMI},
    # migrated off bare require_role:
    "require_listing": {_ADMIN, _SL, _SMI},  # was require_role("schulleitung", "smi")
    "require_user_edit_reader": {_ADMIN, _SMI},  # was require_role("smi")
    "require_audit_reader": {_ADMIN, _SL, _SMI},  # was require_role("schulleitung", "smi")
    "require_import_access": {_ADMIN, _SL, _SMI},  # was require_role(admin, sl, smi)
}

_GATES = {
    "require_admin": require_admin,
    "require_schulleitung": require_schulleitung,
    "require_smi": require_smi,
    "require_manage": require_manage,
    "require_listing": require_listing,
    "require_user_edit_reader": require_user_edit_reader,
    "require_audit_reader": require_audit_reader,
    "require_import_access": require_import_access,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("gate_name", sorted(_GATE_MATRIX))
@pytest.mark.parametrize("caller", sorted(_CALLERS))
async def test_gate_authorization_matches_history(gate_name: str, caller: str) -> None:
    gate = _GATES[gate_name]
    user = _CALLERS[caller]
    should_pass = caller in _GATE_MATRIX[gate_name]
    if should_pass:
        out = await gate(user)
        assert out is user
    else:
        with pytest.raises(HTTPException) as exc:
            await gate(user)
        assert exc.value.status_code == 403


class TestRequireCapability:
    @pytest.mark.asyncio
    async def test_admin_holds_every_capability(self) -> None:
        for cap in Capability:
            out = await require_capability(cap)(_CALLERS[_ADMIN])
            assert out.is_admin

    @pytest.mark.asyncio
    async def test_any_of_semantics(self) -> None:
        # schulleitung holds ORGUNIT_MANAGE but not USER_ADMINISTER; the OR gate passes.
        gate = require_capability(Capability.USER_ADMINISTER, Capability.ORGUNIT_MANAGE)
        out = await gate(_CALLERS[_SL])
        assert _SL in out.roles

    @pytest.mark.asyncio
    async def test_missing_capability_403(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await require_capability(Capability.SYSTEM_ADMINISTER)(_CALLERS[_SL])
        assert exc.value.status_code == 403

    def test_empty_capability_raises(self) -> None:
        with pytest.raises(ValueError):
            require_capability()


class TestEffectiveCapabilities:
    def test_admin_gets_full_set(self) -> None:
        assert effective_capabilities(_CALLERS[_ADMIN]) == frozenset(Capability)

    def test_kl_and_anonymous_hold_nothing(self) -> None:
        assert effective_capabilities(_CALLERS[_KL]) == frozenset()
        assert effective_capabilities(_CALLERS["none"]) == frozenset()

    def test_schulleitung_lacks_user_administer(self) -> None:
        caps = effective_capabilities(_CALLERS[_SL])
        assert Capability.ORGUNIT_MANAGE in caps
        assert Capability.USER_ADMINISTER not in caps

    def test_has_capability_is_admin_short_circuit(self) -> None:
        assert has_capability(_CALLERS[_ADMIN], Capability.SYSTEM_ADMINISTER)
        assert not has_capability(_CALLERS[_SMI], Capability.SYSTEM_ADMINISTER)


class TestImportKindAuthorization:
    """``_authorize_kind`` keeps the per-kind rule after the capability move."""

    @pytest.mark.parametrize("kind", ["students", "teachers"])
    def test_provisioning_kinds_need_user_administer(self, kind: str) -> None:
        # smi (USER_ADMINISTER) and admin pass; schulleitung does not.
        _authorize_kind(_CALLERS[_SMI], kind)
        _authorize_kind(_CALLERS[_ADMIN], kind)
        with pytest.raises(HTTPException) as exc:
            _authorize_kind(_CALLERS[_SL], kind)
        assert exc.value.status_code == 403

    def test_structural_kinds_need_orgunit_manage(self) -> None:
        # schulleitung (ORGUNIT_MANAGE) and admin pass; smi does not.
        _authorize_kind(_CALLERS[_SL], "classes")
        _authorize_kind(_CALLERS[_ADMIN], "classes")
        with pytest.raises(HTTPException) as exc:
            _authorize_kind(_CALLERS[_SMI], "classes")
        assert exc.value.status_code == 403
