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
    def test_admin_requires_null_school(self) -> None:
        from magister_api.schemas.roles import RoleGrantRequest

        RoleGrantRequest(role="admin", school_id=None)  # ok
        with pytest.raises(ValueError):
            RoleGrantRequest(role="admin", school_id=1)

    def test_schulleitung_requires_school(self) -> None:
        from magister_api.schemas.roles import RoleGrantRequest

        RoleGrantRequest(role="schulleitung", school_id=1)  # ok
        with pytest.raises(ValueError):
            RoleGrantRequest(role="schulleitung", school_id=None)

    def test_smi_requires_school(self) -> None:
        from magister_api.schemas.roles import RoleGrantRequest

        RoleGrantRequest(role="smi", school_id=2)  # ok
        with pytest.raises(ValueError):
            RoleGrantRequest(role="smi", school_id=None)

    def test_unknown_role_rejected(self) -> None:
        from magister_api.schemas.roles import RoleGrantRequest

        with pytest.raises(ValueError):
            RoleGrantRequest(role="kl", school_id=1)
        with pytest.raises(ValueError):
            RoleGrantRequest(role="root", school_id=None)
