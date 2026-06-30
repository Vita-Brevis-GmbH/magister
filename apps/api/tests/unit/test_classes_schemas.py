"""ClassCreate / ClassUpdate / ClassOut schema validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from magister_api.schemas.classes import ClassCreate, ClassOut, ClassUpdate


class TestClassCreate:
    def test_valid(self) -> None:
        c = ClassCreate(name="4a", kuerzel="K4A", jahrgangsstufe=4, school_id=1)
        assert c.name == "4a"
        assert c.kuerzel == "K4A"
        assert c.jahrgangsstufe == 4
        assert c.school_id == 1

    def test_kuerzel_optional(self) -> None:
        c = ClassCreate(name="4a", jahrgangsstufe=4)
        assert c.kuerzel is None

    @pytest.mark.parametrize("stufe", [0, 14, -1])
    def test_jahrgangsstufe_out_of_range(self, stufe: int) -> None:
        with pytest.raises(ValidationError):
            ClassCreate(name="4a", jahrgangsstufe=stufe)

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClassCreate(name="", jahrgangsstufe=4)

    def test_long_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClassCreate(name="x" * 65, jahrgangsstufe=4)


class TestClassUpdate:
    def test_all_fields_optional(self) -> None:
        u = ClassUpdate()
        assert u.name is None
        assert u.kuerzel is None

    def test_partial_rename(self) -> None:
        u = ClassUpdate(name="4b")
        assert u.name == "4b"
        assert u.kuerzel is None

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClassUpdate(name="")


class TestClassOut:
    def test_from_attributes(self) -> None:
        class Stub:
            id = 1
            school_id = 7
            name = "4a"
            kuerzel = "K4A"
            jahrgangsstufe = 4
            details = None
            status = "active"
            created_at = datetime.now(UTC)
            updated_at = datetime.now(UTC)

        out = ClassOut.model_validate(Stub())
        assert out.id == 1
        assert out.status == "active"
