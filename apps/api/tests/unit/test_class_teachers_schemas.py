"""ClassTeacherCreate / ClassTeacherOut schema validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from magister_api.schemas.class_teachers import ClassTeacherCreate


class TestClassTeacherCreate:
    def test_valid_haupt(self) -> None:
        c = ClassTeacherCreate(
            ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
            role="haupt",
            valid_from=datetime.now(UTC),
        )
        assert c.role == "haupt"
        assert c.valid_to is None

    @pytest.mark.parametrize("role", ["haupt", "co", "stellvertretung"])
    def test_all_allowed_roles(self, role: str) -> None:
        c = ClassTeacherCreate(
            ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
            role=role,
            valid_from=datetime.now(UTC),
        )
        assert c.role == role

    def test_unknown_role_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClassTeacherCreate(
                ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
                role="ersatzlehrer",
                valid_from=datetime.now(UTC),
            )

    def test_invalid_object_guid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClassTeacherCreate(
                ad_object_guid="not-a-guid",
                role="haupt",
                valid_from=datetime.now(UTC),
            )

    def test_role_default_is_haupt(self) -> None:
        c = ClassTeacherCreate(
            ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
            valid_from=datetime.now(UTC),
        )
        assert c.role == "haupt"

    def test_valid_to_optional(self) -> None:
        now = datetime.now(UTC)
        c = ClassTeacherCreate(
            ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
            valid_from=now,
            valid_to=now + timedelta(days=30),
        )
        assert c.valid_to is not None
