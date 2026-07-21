"""Re-assign a student's Zyklus AD groups when their grade year changes.

When a student is promoted / moved into a new grade year (Schuljahr) that falls
into a different Zyklus, their default AD groups must follow: the old Zyklus's
template groups are removed and the new Zyklus's template groups added. Only the
groups that actually differ between the two templates are touched, so any
manually-assigned groups (or groups shared across Zyklen) are preserved.

Best-effort by design: AD write failures are swallowed (the class change itself
already happened in the DB) — a flaky DC must never block a promotion. Each
student whose groups change gets one ``student_groups_reassigned`` audit event.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.ou import select_provision_groups, zyklus_for_jahrgangsstufe
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School


@dataclass(frozen=True)
class GradeChange:
    """A single student's grade-year transition captured during a class change."""

    ad_object_guid: str
    old_grade: int | None
    new_grade: int


async def reassign_cycle_groups(
    session: AsyncSession,
    settings: Settings,
    ad_client: AdClient | None,
    changes: list[GradeChange],
    *,
    actor_upn: str,
    actor_object_guid: str | None,
    ip: str | None,
    request_id: str,
) -> int:
    """Swap Zyklus template groups for students whose grade crossed a Zyklus.

    No-op (returns 0) when there is no AD client, no changes, or the settings
    row is missing. Returns the number of students whose AD groups were changed.
    """
    if ad_client is None or not changes:
        return 0
    app = await session.get(AppSettings, 1)
    if app is None:
        return 0

    # Zyklus boundaries stay global (Lehrplan 21); only the group templates that
    # are applied are per-school.
    z1_max = app.zyklus1_max_grade
    z2_max = app.zyklus2_max_grade

    def groups_for(school: School, zyklus: int) -> list[str]:
        return select_provision_groups(
            kind="student",
            zyklus=zyklus,
            groups_teacher=school.ad_groups_teacher or [],
            groups_student_zyklus1=school.ad_groups_student_zyklus1 or [],
            groups_student_zyklus2=school.ad_groups_student_zyklus2 or [],
            groups_student_zyklus3=school.ad_groups_student_zyklus3 or [],
        )

    audit = AuditService(session, settings)
    changed = 0
    for ch in changes:
        old_zyklus = (
            None
            if ch.old_grade is None
            else zyklus_for_jahrgangsstufe(ch.old_grade, zyklus1_max=z1_max, zyklus2_max=z2_max)
        )
        new_zyklus = zyklus_for_jahrgangsstufe(ch.new_grade, zyklus1_max=z1_max, zyklus2_max=z2_max)
        if old_zyklus == new_zyklus:
            continue  # Same Zyklus → template groups unchanged.

        student = await session.get(AdUserCache, ch.ad_object_guid)
        if student is None or student.school_id is None:
            continue
        school = await session.get(School, student.school_id)
        if school is None:
            continue

        old_groups = [] if old_zyklus is None else groups_for(school, old_zyklus)
        new_groups = groups_for(school, new_zyklus)
        to_add = [g for g in new_groups if g not in old_groups]
        to_remove = [g for g in old_groups if g not in new_groups]
        if not to_add and not to_remove:
            continue

        dn = await ad_client.find_user_dn(ch.ad_object_guid)
        if dn is None:
            continue  # Not in AD (yet) — nothing to write.

        failed_add = (
            await ad_client.add_user_to_groups(user_dn=dn, group_dns=to_add) if to_add else []
        )
        failed_remove = (
            await ad_client.remove_user_from_groups(user_dn=dn, group_dns=to_remove)
            if to_remove
            else []
        )
        added = [g for g in to_add if g not in failed_add]
        removed = [g for g in to_remove if g not in failed_remove]
        if not added and not removed:
            continue

        # Keep the memberOf cache in sync with what actually landed in AD.
        current = set(student.ad_groups or [])
        current |= set(added)
        current -= set(removed)
        student.ad_groups = sorted(current)
        await session.flush()

        await audit.emit(
            action="student_groups_reassigned",
            target_kind="user",
            target_id=ch.ad_object_guid,
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=student.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "old_zyklus": old_zyklus,
                "new_zyklus": new_zyklus,
                "added": added,
                "removed": removed,
            },
        )
        changed += 1
    return changed


__all__ = ["GradeChange", "reassign_cycle_groups"]
