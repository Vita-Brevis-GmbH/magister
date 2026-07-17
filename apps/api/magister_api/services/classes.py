"""ClassService: orchestrates ClassRepository + AuditService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.class_memberships import ClassMembershipRepository
from magister_api.repositories.classes import ClassRepository

# Grade bounds: -1 = 1. Kindergarten, 0 = 2. Kindergarten, 1..13 = Klassen.
_GRADE_MIN = -1
_GRADE_MAX = 13


class ClassNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PromotionResult:
    students_moved: int
    students_failed: int
    errors: list[tuple[str, str]]
    source_archived: bool


class ClassPermissionError(PermissionError):
    """Raised on cross-school write attempts (Schulleitung A → School B)."""


class ClassGradeRangeError(ValueError):
    """Raised when jahrgangsstufe_bis < jahrgangsstufe on an update."""


class ClassService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = ClassRepository(session, scope)
        self.audit = AuditService(session, settings)

    async def list_active(self) -> list[SchoolClass]:
        return await self.repo.list_active()

    async def get(self, class_id: int) -> SchoolClass:
        row = await self.repo.get(class_id)
        if row is None:
            raise ClassNotFoundError(str(class_id))
        return row

    async def create(
        self,
        *,
        school_id: int,
        name: str,
        kuerzel: str | None,
        jahrgangsstufe: int,
        jahrgangsstufe_bis: int | None = None,
        details: str | None = None,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        try:
            row = await self.repo.create(
                school_id=school_id,
                name=name,
                kuerzel=kuerzel,
                jahrgangsstufe=jahrgangsstufe,
                jahrgangsstufe_bis=jahrgangsstufe_bis,
                details=details,
            )
        except PermissionError as exc:
            raise ClassPermissionError("school_out_of_scope") from exc
        await self.audit.emit(
            action="class_created",
            target_kind="class",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "name": row.name,
                "kuerzel": row.kuerzel,
                "jahrgangsstufe": row.jahrgangsstufe,
                "jahrgangsstufe_bis": row.jahrgangsstufe_bis,
            },
        )
        return row

    async def rename(
        self,
        *,
        class_id: int,
        new_name: str | None,
        new_kuerzel: str | None,
        new_details: str | None = None,
        new_jahrgangsstufe: int | None = None,
        set_jahrgangsstufe_bis: bool = False,
        new_jahrgangsstufe_bis: int | None = None,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        row = await self.get(class_id)
        old_name = row.name
        old_kuerzel = row.kuerzel
        old_details = row.details

        # Validate the effective grade range against whatever ends up on the row.
        effective_von = new_jahrgangsstufe if new_jahrgangsstufe is not None else row.jahrgangsstufe
        effective_bis = new_jahrgangsstufe_bis if set_jahrgangsstufe_bis else row.jahrgangsstufe_bis
        if effective_bis is not None and effective_bis < effective_von:
            raise ClassGradeRangeError("jahrgangsstufe_bis must be >= jahrgangsstufe")

        row, cache_relevant_changed = await self.repo.update(
            row,
            name=new_name,
            kuerzel=new_kuerzel,
            details=new_details,
            jahrgangsstufe=new_jahrgangsstufe,
            set_jahrgangsstufe_bis=set_jahrgangsstufe_bis,
            jahrgangsstufe_bis=new_jahrgangsstufe_bis,
        )
        kuerzel_changed = new_kuerzel is not None and new_kuerzel != old_kuerzel
        details_changed = new_details is not None and new_details != old_details
        if cache_relevant_changed or kuerzel_changed or details_changed:
            await self.audit.emit(
                action="class_renamed",
                target_kind="class",
                target_id=str(row.id),
                actor_upn=self.scope.upn,
                actor_object_guid=self.scope.ad_object_guid,
                school_id=row.school_id,
                ip=ip,
                request_id=request_id,
                payload={
                    "old_name": old_name,
                    "new_name": row.name,
                    "old_kuerzel": old_kuerzel,
                    "new_kuerzel": row.kuerzel,
                    "details_changed": details_changed,
                    "jahrgangsstufe": row.jahrgangsstufe,
                    "jahrgangsstufe_bis": row.jahrgangsstufe_bis,
                },
            )
        return row

    async def archive(
        self,
        *,
        class_id: int,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        row = await self.get(class_id)
        row = await self.repo.archive(row)
        await self.audit.emit(
            action="class_archived",
            target_kind="class",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload={"name": row.name, "jahrgangsstufe": row.jahrgangsstufe},
        )
        return row

    async def promote(
        self,
        *,
        source_class_id: int,
        target_class_id: int,
        archive_source: bool,
        student_guids: list[str] | None = None,
        grade_overrides: dict[str, int] | None = None,
        bump_grade: bool = True,
        ip: str | None,
        request_id: str,
    ) -> PromotionResult:
        """Move active students from source to target class.

        With ``student_guids`` only those (active) students are moved; None
        moves all active students. Uses savepoints per student (same as
        bulk_add) so partial failures don't roll back the whole batch.

        Each moved student's own ``jahrgangsstufe`` is advanced when
        ``bump_grade`` is set: by default +1 (from the student's grade, or the
        source class's grade when the student has none), clamped to the valid
        range. ``grade_overrides`` maps ``ad_object_guid -> explicit new grade``
        for the exceptions (staying, skipping). After the move an optional
        archive of the source class is performed and one audit event emitted.
        """
        overrides = grade_overrides or {}
        source = await self.get(source_class_id)
        target = await self.get(target_class_id)
        membership_repo = ClassMembershipRepository(self.session)
        active = await membership_repo.list_for_class(source_class_id, only_active=True)
        if student_guids is not None:
            wanted = set(student_guids)
            active = [m for m in active if m.ad_object_guid in wanted]

        moved: list[int] = []
        errors: list[tuple[str, str]] = []
        now_iso = None

        for m in active:
            sp = await self.session.begin_nested()
            try:
                effective_from = utcnow()
                if now_iso is None:
                    now_iso = effective_from.isoformat()
                clamp_at = effective_from - timedelta(seconds=1)

                # Close old memberships in other classes.
                closed = await membership_repo.end_active_for_student(
                    ad_object_guid=m.ad_object_guid,
                    end_at=effective_from,
                    excluding_class_id=target_class_id,
                )
                for row in closed:
                    row.valid_to = clamp_at
                if closed:
                    await self.session.flush()

                # Reject if student is already active in target.
                overlapping = await membership_repo.find_overlapping(
                    ad_object_guid=m.ad_object_guid,
                    valid_from=effective_from,
                    valid_to=None,
                )
                if overlapping:
                    await sp.rollback()
                    errors.append((m.ad_object_guid, "overlapping_membership"))
                    continue

                new_row = ClassMembership(
                    class_id=target_class_id,
                    ad_object_guid=m.ad_object_guid,
                    valid_from=effective_from,
                    valid_to=None,
                    created_by=self.scope.upn,
                )
                self.session.add(new_row)
                await self.session.flush()

                # Advance the student's own grade. Override wins; else +1 from
                # the student's grade (fallback: the source class's grade).
                # scope-bypass: the source class was already scope-checked via
                # get(); we only touch students being promoted out of it.
                if bump_grade or m.ad_object_guid in overrides:
                    student = await self.session.get(AdUserCache, m.ad_object_guid)
                    if student is not None:
                        if m.ad_object_guid in overrides:
                            new_grade = overrides[m.ad_object_guid]
                        else:
                            base = (
                                student.jahrgangsstufe
                                if student.jahrgangsstufe is not None
                                else source.jahrgangsstufe
                            )
                            new_grade = base + 1
                        student.jahrgangsstufe = max(_GRADE_MIN, min(_GRADE_MAX, new_grade))
                        await self.session.flush()

                await sp.commit()
                moved.append(new_row.id)
            except Exception:
                await sp.rollback()
                errors.append((m.ad_object_guid, "unexpected_error"))

        source_archived = False
        if archive_source:
            source = await self.repo.archive(source)
            source_archived = True

        await self.audit.emit(
            action="class_promoted",
            target_kind="class",
            target_id=str(source_class_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=source.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "source_class_id": source_class_id,
                "source_class_name": source.name,
                "target_class_id": target_class_id,
                "target_class_name": target.name,
                "students_moved": len(moved),
                "students_failed": len(errors),
                "source_archived": source_archived,
                "selected_subset": student_guids is not None,
            },
        )
        return PromotionResult(
            students_moved=len(moved),
            students_failed=len(errors),
            errors=errors,
            source_archived=source_archived,
        )

    async def advance_students(
        self,
        *,
        source_class_id: int,
        student_guids: list[str],
        grade_delta: int = 0,
        target_class_id: int | None = None,
        archive_source: bool = False,
        ip: str | None,
        request_id: str,
    ) -> PromotionResult:
        """Move and/or re-grade selected students of a class.

        Powers the class-detail multi-select actions:
        - ``target_class_id`` set and different from the source → move each
          student to that class (any direction: higher, lower, same level).
        - ``target_class_id`` None or equal to the source → keep the class; only
          the grade changes (raise the school year without changing the class).
        - ``grade_delta`` shifts each student's own ``jahrgangsstufe`` by that
          amount (e.g. +1 school-year change, -1 down, 0 keep), clamped to range.

        Per-student savepoints; one audit event. Same scope rules as promote.
        """
        source = await self.get(source_class_id)
        moving = target_class_id is not None and target_class_id != source_class_id
        if moving:
            assert target_class_id is not None  # narrowed by `moving`
            target = await self.get(target_class_id)
        else:
            target = source
        membership_repo = ClassMembershipRepository(self.session)
        active = await membership_repo.list_for_class(source_class_id, only_active=True)
        wanted = set(student_guids)
        active = [m for m in active if m.ad_object_guid in wanted]

        moved: list[str] = []
        errors: list[tuple[str, str]] = []

        for m in active:
            sp = await self.session.begin_nested()
            try:
                if moving:
                    effective_from = utcnow()
                    clamp_at = effective_from - timedelta(seconds=1)
                    closed = await membership_repo.end_active_for_student(
                        ad_object_guid=m.ad_object_guid,
                        end_at=effective_from,
                        excluding_class_id=target.id,
                    )
                    for row in closed:
                        row.valid_to = clamp_at
                    if closed:
                        await self.session.flush()
                    overlapping = await membership_repo.find_overlapping(
                        ad_object_guid=m.ad_object_guid,
                        valid_from=effective_from,
                        valid_to=None,
                    )
                    if overlapping:
                        await sp.rollback()
                        errors.append((m.ad_object_guid, "overlapping_membership"))
                        continue
                    self.session.add(
                        ClassMembership(
                            class_id=target.id,
                            ad_object_guid=m.ad_object_guid,
                            valid_from=effective_from,
                            valid_to=None,
                            created_by=self.scope.upn,
                        )
                    )
                    await self.session.flush()

                if grade_delta != 0:
                    # scope-bypass: source class already scope-checked via get();
                    # only students being advanced out of it are touched.
                    student = await self.session.get(AdUserCache, m.ad_object_guid)
                    if student is not None:
                        base = (
                            student.jahrgangsstufe
                            if student.jahrgangsstufe is not None
                            else source.jahrgangsstufe
                        )
                        new_grade = base + grade_delta
                        student.jahrgangsstufe = max(_GRADE_MIN, min(_GRADE_MAX, new_grade))
                        await self.session.flush()

                await sp.commit()
                moved.append(m.ad_object_guid)
            except Exception:  # noqa: BLE001
                await sp.rollback()
                errors.append((m.ad_object_guid, "unexpected_error"))

        source_archived = False
        if archive_source and moving:
            source = await self.repo.archive(source)
            source_archived = True

        await self.audit.emit(
            action="class_students_advanced",
            target_kind="class",
            target_id=str(source_class_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=source.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "source_class_id": source_class_id,
                "source_class_name": source.name,
                "target_class_id": target.id if moving else None,
                "target_class_name": target.name if moving else None,
                "grade_delta": grade_delta,
                "students_moved": len(moved),
                "students_failed": len(errors),
                "source_archived": source_archived,
            },
        )
        return PromotionResult(
            students_moved=len(moved),
            students_failed=len(errors),
            errors=errors,
            source_archived=source_archived,
        )
