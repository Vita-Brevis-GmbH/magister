"""Login-group membership matching for the direct AD-credential login."""

from __future__ import annotations

import pytest

from magister_api.ad.client import _is_member_of_group


class TestIsMemberOfGroup:
    MEMBER_OF = [
        "CN=Magister-Login,OU=Groups,DC=schule,DC=local",
        "CN=Alle-Lehrer,OU=Groups,DC=schule,DC=local",
    ]

    def test_full_dn_match(self) -> None:
        assert _is_member_of_group(self.MEMBER_OF, "CN=Magister-Login,OU=Groups,DC=schule,DC=local")

    def test_full_dn_match_case_insensitive(self) -> None:
        assert _is_member_of_group(self.MEMBER_OF, "cn=magister-login,ou=groups,dc=schule,dc=local")

    def test_bare_cn_match(self) -> None:
        assert _is_member_of_group(self.MEMBER_OF, "Magister-Login")

    def test_bare_cn_match_case_insensitive(self) -> None:
        assert _is_member_of_group(self.MEMBER_OF, "magister-login")

    def test_non_member(self) -> None:
        assert not _is_member_of_group(self.MEMBER_OF, "CN=Admins,OU=Groups,DC=schule,DC=local")
        assert not _is_member_of_group(self.MEMBER_OF, "Admins")

    def test_single_string_memberof(self) -> None:
        assert _is_member_of_group(
            "CN=Magister-Login,OU=Groups,DC=schule,DC=local", "Magister-Login"
        )

    def test_empty_memberof(self) -> None:
        assert not _is_member_of_group(None, "Magister-Login")
        assert not _is_member_of_group([], "Magister-Login")

    def test_empty_group_never_matches(self) -> None:
        assert not _is_member_of_group(self.MEMBER_OF, "")
        assert not _is_member_of_group(self.MEMBER_OF, "   ")


class TestRoleGrantValidation:
    """ADR-0010: role validity + the admin/scoped-role scope rule moved from the
    schema to the DB-aware router (roles are dynamic now), so the schema only
    enforces the request *shape*. The scope/role-validity rules are covered
    end-to-end in ``tests/integration/test_admin_rbac.py``.
    """

    def test_shape_accepts_any_role_string(self) -> None:
        from magister_api.schemas.roles import RoleGrantRequest

        # A custom role key with a school_id is a valid *shape*; whether it is
        # assignable is decided by the router against the DB catalog.
        req = RoleGrantRequest(role="teamlead", school_id=1)
        assert req.role == "teamlead"
        assert RoleGrantRequest(role="admin", school_id=None).school_id is None

    def test_empty_role_rejected(self) -> None:
        from pydantic import ValidationError

        from magister_api.schemas.roles import RoleGrantRequest

        with pytest.raises(ValidationError):
            RoleGrantRequest(role="", school_id=1)
