"""Target-OU selection for AD account provisioning.

Pure helpers (no I/O) so they are trivially unit-testable. The student OU is
picked from the class's Zyklus, derived from its ``jahrgangsstufe`` and the
configurable boundaries (see ``app_settings.zyklus{1,2}_max_grade``):

- Zyklus 1: grades ≤ ``zyklus1_max``
- Zyklus 2: ``zyklus1_max`` < grade ≤ ``zyklus2_max``
- Zyklus 3: grade > ``zyklus2_max``

Defaults follow Lehrplan 21 (Z1: 1-2, Z2: 3-6, Z3: 7+). For OU routing only two
buckets matter: Zyklus 3 gets its own OU, everything else the "other" OU.
"""

from __future__ import annotations

DEFAULT_ZYKLUS1_MAX = 2
DEFAULT_ZYKLUS2_MAX = 6


def zyklus_for_jahrgangsstufe(
    jahrgangsstufe: int,
    *,
    zyklus1_max: int = DEFAULT_ZYKLUS1_MAX,
    zyklus2_max: int = DEFAULT_ZYKLUS2_MAX,
) -> int:
    """Map a grade to a Zyklus (1, 2 or 3) using the configured boundaries."""
    if jahrgangsstufe <= zyklus1_max:
        return 1
    if jahrgangsstufe <= zyklus2_max:
        return 2
    return 3


def select_student_ou(
    *,
    jahrgangsstufe: int,
    ou_zyklus3: str | None,
    ou_other: str | None,
    zyklus1_max: int = DEFAULT_ZYKLUS1_MAX,
    zyklus2_max: int = DEFAULT_ZYKLUS2_MAX,
) -> str | None:
    """OU a student of the given class-grade should be created in.

    Returns ``None`` if the applicable OU is not configured, so the caller can
    refuse provisioning rather than write to a wrong or empty OU.
    """
    zyklus = zyklus_for_jahrgangsstufe(
        jahrgangsstufe, zyklus1_max=zyklus1_max, zyklus2_max=zyklus2_max
    )
    if zyklus == 3:
        return ou_zyklus3 or None
    return ou_other or None


def select_provision_groups(
    *,
    kind: str,
    zyklus: int | None,
    groups_teacher: list[str],
    groups_student_zyklus1: list[str],
    groups_student_zyklus2: list[str],
    groups_student_zyklus3: list[str],
) -> list[str]:
    """Default AD groups for a newly provisioned account.

    Teachers get the teacher template; students get the template for their
    Zyklus (1/2/3). ``zyklus`` is ignored for teachers.
    """
    if kind == "teacher":
        return list(groups_teacher)
    if zyklus == 1:
        return list(groups_student_zyklus1)
    if zyklus == 2:
        return list(groups_student_zyklus2)
    return list(groups_student_zyklus3)


__all__ = [
    "DEFAULT_ZYKLUS1_MAX",
    "DEFAULT_ZYKLUS2_MAX",
    "select_provision_groups",
    "select_student_ou",
    "zyklus_for_jahrgangsstufe",
]
