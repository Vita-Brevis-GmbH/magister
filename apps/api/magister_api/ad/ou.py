"""Target-OU selection for AD account provisioning.

Pure helpers (no I/O) so they are trivially unit-testable. The student OU is
picked from the class's Zyklus, derived from its ``jahrgangsstufe``:

- Zyklus 1: grades 1-2
- Zyklus 2: grades 3-6
- Zyklus 3: grades 7-9 (Sekundarstufe I)

For OU routing only two buckets matter: Zyklus 3 gets its own OU, everything
else (Zyklus 1/2, and any grade >= 10) lands in the "other students" OU.
"""

from __future__ import annotations

ZYKLUS_3_MIN_JAHRGANGSSTUFE = 7


def zyklus_for_jahrgangsstufe(jahrgangsstufe: int) -> int:
    """Map a grade (1..13) to a Lehrplan-21 Zyklus (1, 2 or 3)."""
    if jahrgangsstufe <= 2:
        return 1
    if jahrgangsstufe <= 6:
        return 2
    return 3


def select_student_ou(
    *,
    jahrgangsstufe: int,
    ou_zyklus3: str | None,
    ou_other: str | None,
) -> str | None:
    """OU a student of the given class-grade should be created in.

    Returns ``None`` if the applicable OU is not configured, so the caller can
    refuse provisioning rather than write to a wrong or empty OU.
    """
    if jahrgangsstufe >= ZYKLUS_3_MIN_JAHRGANGSSTUFE:
        return ou_zyklus3 or None
    return ou_other or None


__all__ = [
    "ZYKLUS_3_MIN_JAHRGANGSSTUFE",
    "select_student_ou",
    "zyklus_for_jahrgangsstufe",
]
