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

    @pytest.mark.parametrize("stufe", [-2, 14, 99])
    def test_jahrgangsstufe_out_of_range(self, stufe: int) -> None:
        with pytest.raises(ValidationError):
            ClassCreate(name="4a", jahrgangsstufe=stufe)

    @pytest.mark.parametrize("stufe", [-1, 0])
    def test_kindergarten_grades_allowed(self, stufe: int) -> None:
        # -1 = 1. Kindergarten, 0 = 2. Kindergarten.
        c = ClassCreate(name="Basisstufe", jahrgangsstufe=stufe)
        assert c.jahrgangsstufe == stufe

    def test_grade_range_accepted(self) -> None:
        c = ClassCreate(name="Mehrklasse", jahrgangsstufe=1, jahrgangsstufe_bis=3)
        assert c.jahrgangsstufe == 1
        assert c.jahrgangsstufe_bis == 3

    def test_inverted_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClassCreate(name="Bad", jahrgangsstufe=5, jahrgangsstufe_bis=3)

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
            jahrgangsstufe_bis = None
            details = None
            status = "active"
            created_at = datetime.now(UTC)
            updated_at = datetime.now(UTC)

        out = ClassOut.model_validate(Stub())
        assert out.id == 1
        assert out.status == "active"
