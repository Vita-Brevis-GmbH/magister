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

    def test_custom_boundaries_shift_zyklus3(self) -> None:
        # With z2_max=8, grade 7 is Zyklus 2 → "other" OU, grade 9 is Zyklus 3.
        assert zyklus_for_jahrgangsstufe(7, zyklus1_max=4, zyklus2_max=8) == 2
        assert zyklus_for_jahrgangsstufe(9, zyklus1_max=4, zyklus2_max=8) == 3
        assert (
            select_student_ou(
                jahrgangsstufe=7,
                ou_zyklus3="OU=Z3,DC=x",
                ou_other="OU=Other,DC=x",
                zyklus1_max=4,
                zyklus2_max=8,
            )
            == "OU=Other,DC=x"
        )
        assert (
            select_student_ou(
                jahrgangsstufe=9,
                ou_zyklus3="OU=Z3,DC=x",
                ou_other="OU=Other,DC=x",
                zyklus1_max=4,
                zyklus2_max=8,
            )
            == "OU=Z3,DC=x"
        )
