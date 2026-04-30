"""UPN and objectGUID validators."""

from __future__ import annotations

import pytest

from magister_api.schemas.common import validate_object_guid, validate_upn


class TestUpn:
    @pytest.mark.parametrize(
        "value",
        [
            "user@example.ch",
            "Anna.Beispiel@schule-zh.ch",
            "kl_42@bezirk.example.com",
        ],
    )
    def test_accepts(self, value: str) -> None:
        assert validate_upn(value) == value.lower()

    @pytest.mark.parametrize(
        "value",
        [
            "no-at-sign",
            "missing@domain",
            "two@@at.example.ch",
            "  spaced @example.ch",
            "",
            "user@.ch",
            "user@example",
        ],
    )
    def test_rejects(self, value: str) -> None:
        with pytest.raises(ValueError):
            validate_upn(value)


class TestObjectGuid:
    def test_accepts_canonical(self) -> None:
        v = "01020304-0506-0708-090a-0b0c0d0e0f10"
        assert validate_object_guid(v) == v

    def test_strips_braces(self) -> None:
        v = "{01020304-0506-0708-090a-0b0c0d0e0f10}"
        assert validate_object_guid(v) == v.strip("{}").lower()

    def test_lowercases(self) -> None:
        v = "01020304-ABCD-0708-090A-0B0C0D0E0F10"
        assert validate_object_guid(v) == v.lower()

    @pytest.mark.parametrize(
        "value",
        [
            "not-a-guid",
            "01020304-0506-0708-090a-0b0c0d0e0f1",  # too short
            "01020304-0506-0708-090a-0b0c0d0e0f1011",  # too long
            "01020304_0506_0708_090a_0b0c0d0e0f10",  # underscores
        ],
    )
    def test_rejects(self, value: str) -> None:
        with pytest.raises(ValueError):
            validate_object_guid(value)
