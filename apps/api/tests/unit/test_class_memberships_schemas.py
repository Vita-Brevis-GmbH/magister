"""ClassMembershipCreate / Out schema validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from magister_api.schemas.class_memberships import ClassMembershipCreate


class TestClassMembershipCreate:
    def test_minimal(self) -> None:
        c = ClassMembershipCreate(ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10")
        assert c.valid_from is None  # service defaults to now
        assert c.valid_to is None

    def test_with_window(self) -> None:
        now = datetime.now(UTC)
        c = ClassMembershipCreate(
            ad_object_guid="01020304-0506-0708-090a-0b0c0d0e0f10",
            valid_from=now,
            valid_to=now + timedelta(days=30),
        )
        assert c.valid_from == now
        assert c.valid_to is not None

    def test_invalid_object_guid(self) -> None:
        with pytest.raises(ValidationError):
            ClassMembershipCreate(ad_object_guid="not-a-guid")
