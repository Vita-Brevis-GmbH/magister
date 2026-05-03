"""Unit tests for the LDAP entry parser + GUID decoder."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from magister_api.ad.client import (
    UAC_ACCOUNTDISABLE,
    AdUserRecord,
    _decode_object_guid,
    _kind_from_member_of,
    parse_ad_entry,
)
from magister_api.ad.errors import AdUserParseError


class TestDecodeObjectGuid:
    def test_canonical_string_passthrough(self) -> None:
        v = "01020304-0506-0708-090a-0b0c0d0e0f10"
        assert _decode_object_guid(v) == v

    def test_uppercase_string_lowercased(self) -> None:
        v = "01020304-0506-0708-090A-0B0C0D0E0F10"
        assert _decode_object_guid(v) == v.lower()

    def test_uuid_object(self) -> None:
        u = uuid.UUID("12345678-90ab-cdef-1234-567890abcdef")
        assert _decode_object_guid(u) == str(u)

    def test_ad_le_blob(self) -> None:
        u = uuid.UUID("12345678-90ab-cdef-1234-567890abcdef")
        decoded = _decode_object_guid(u.bytes_le)
        assert decoded == str(u)

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            _decode_object_guid("not-a-guid")

    def test_invalid_byte_length_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            _decode_object_guid(b"\x00" * 5)

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            _decode_object_guid(12345)  # type: ignore[arg-type]


class TestKindFromMemberOf:
    def test_default_student(self) -> None:
        assert _kind_from_member_of(None) == "student"
        assert _kind_from_member_of([]) == "student"

    def test_teacher(self) -> None:
        assert _kind_from_member_of(["CN=Teachers,OU=Groups"]) == "teacher"
        assert _kind_from_member_of(["cn=Lehrer,OU=Groups"]) == "teacher"

    def test_admin_wins_over_teacher(self) -> None:
        groups = ["CN=Admins,OU=Groups", "CN=Teachers,OU=Groups"]
        assert _kind_from_member_of(groups) == "admin"


class TestParseAdEntry:
    def _attrs(self, **overrides: Any) -> dict[str, Any]:
        guid_le = uuid.UUID("aabbccdd-eeff-0011-2233-445566778899").bytes_le
        base = {
            "objectGUID": guid_le,
            "userPrincipalName": "anna@example.ch",
            "givenName": "Anna",
            "sn": "Beispiel",
            "mail": "anna@example.ch",
            "userAccountControl": 0x200,
            "memberOf": [],
        }
        base.update(overrides)
        return base

    def test_happy_path(self) -> None:
        rec = parse_ad_entry(self._attrs(), "CN=Anna,OU=A,DC=schule,DC=local")
        assert isinstance(rec, AdUserRecord)
        assert rec.upn == "anna@example.ch"
        assert rec.given_name == "Anna"
        assert rec.surname == "Beispiel"
        assert rec.enabled is True
        assert rec.kind == "student"
        assert rec.distinguished_name == "CN=Anna,OU=A,DC=schule,DC=local"

    def test_disabled_account(self) -> None:
        rec = parse_ad_entry(
            self._attrs(userAccountControl=0x200 | UAC_ACCOUNTDISABLE),
            "CN=X,DC=schule,DC=local",
        )
        assert rec.enabled is False

    def test_missing_upn_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            parse_ad_entry(self._attrs(userPrincipalName=None), "CN=X")

    def test_missing_object_guid_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            parse_ad_entry(self._attrs(objectGUID=None), "CN=X")

    def test_member_of_string_normalised(self) -> None:
        rec = parse_ad_entry(
            self._attrs(memberOf="CN=Teachers,OU=Groups"),
            "CN=X",
        )
        assert rec.kind == "teacher"

    def test_school_match_via_ou(self) -> None:
        rec = parse_ad_entry(
            self._attrs(),
            "CN=Anna,OU=Students,OU=ALPHA,DC=schule,DC=local",
        )
        assert rec.matches_school_via_ou("alpha") is True
        assert rec.matches_school_via_ou("beta") is False
