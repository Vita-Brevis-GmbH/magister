"""Zyklus derivation + target-OU selection for provisioning."""

from __future__ import annotations

import pytest

from magister_api.ad.ou import select_student_ou, zyklus_for_jahrgangsstufe


@pytest.mark.parametrize(
    ("jhg", "expected"),
    [(1, 1), (2, 1), (3, 2), (6, 2), (7, 3), (9, 3), (13, 3)],
)
def test_zyklus_mapping(jhg: int, expected: int) -> None:
    assert zyklus_for_jahrgangsstufe(jhg) == expected


class TestSelectStudentOu:
    def test_zyklus3_grade_uses_z3_ou(self) -> None:
        ou = select_student_ou(jahrgangsstufe=8, ou_zyklus3="OU=Z3,DC=x", ou_other="OU=Other,DC=x")
        assert ou == "OU=Z3,DC=x"

    def test_lower_grade_uses_other_ou(self) -> None:
        ou = select_student_ou(jahrgangsstufe=4, ou_zyklus3="OU=Z3,DC=x", ou_other="OU=Other,DC=x")
        assert ou == "OU=Other,DC=x"

    def test_missing_z3_ou_returns_none(self) -> None:
        assert (
            select_student_ou(jahrgangsstufe=9, ou_zyklus3=None, ou_other="OU=Other,DC=x") is None
        )

    def test_missing_other_ou_returns_none(self) -> None:
        assert select_student_ou(jahrgangsstufe=2, ou_zyklus3="OU=Z3,DC=x", ou_other="") is None
