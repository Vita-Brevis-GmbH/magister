"""Validation rules for UserAttributesUpdate."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from magister_api.schemas.user_attrs import UserAttributesUpdate


class TestUpn:
    def test_lowercased_and_trimmed(self) -> None:
        p = UserAttributesUpdate.model_validate({"upn": "  Anna.Lehrer@Schule.ch  "})
        assert p.upn == "anna.lehrer@schule.ch"

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"upn": ""})

    def test_missing_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"upn": "anna"})

    def test_illegal_local_part_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"upn": "an<na>@x.ch"})


class TestSam:
    def test_alnum_with_dot(self) -> None:
        p = UserAttributesUpdate.model_validate({"sam_account_name": "anna.b"})
        assert p.sam_account_name == "anna.b"

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"sam_account_name": "anna b"})

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"sam_account_name": "a" * 21})

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"sam_account_name": ""})


class TestMail:
    def test_lowercased(self) -> None:
        p = UserAttributesUpdate.model_validate({"mail": "Anna.B@Schule.ch"})
        assert p.mail == "anna.b@schule.ch"

    def test_empty_string_clears(self) -> None:
        p = UserAttributesUpdate.model_validate({"mail": ""})
        assert p.mail == ""

    def test_null_clears(self) -> None:
        p = UserAttributesUpdate.model_validate({"mail": None})
        assert p.mail is None


class TestExtraFields:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserAttributesUpdate.model_validate({"surname": "X"})  # surname not editable here
