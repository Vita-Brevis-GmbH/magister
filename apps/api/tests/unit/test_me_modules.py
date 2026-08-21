"""M6 Phase 0: GET /me/modules exposes the enabled feature modules."""

from __future__ import annotations

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.routers.me import my_modules


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        ad_object_guid="00000000-0000-0000-0000-000000000000",
        upn="teacher@schule.test",
        is_admin=False,
        school_scope=(1,),
        roles=(),
        expires_at=None,
    )


async def test_my_modules_lists_enabled_modules() -> None:
    out = await my_modules(user=_user())
    assert [m.id for m in out.modules] == ["platform", "school"]


async def test_my_modules_reports_dependencies() -> None:
    out = await my_modules(user=_user())
    school = next(m for m in out.modules if m.id == "school")
    assert "platform" in school.depends_on
