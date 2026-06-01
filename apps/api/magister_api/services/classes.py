"""ClassService: orchestrates ClassRepository + AuditService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.class_memberships import ClassMembershipRepository
from magister_api.repositories.classes import ClassRepository


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
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        try:
            row = await self.repo.create(
                school_id=school_id,
                name=name,
                kuerzel=kuerzel,
                jahrgangsstufe=jahrgangsstufe,
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
            },
        )
        return row

    async def rename(
        self,
        *,
        class_id: int,
        new_name: str | None,
        new_kuerzel: str | None,
        ip: str | None,
        request_id: str,
    ) -> SchoolClass:
        row = await self.get(class_id)
        old_name = row.name
        old_kuerzel = row.kuerzel
        row, name_changed = await self.repo.update(row, name=new_name, kuerzel=new_kuerzel)
        if name_changed or (new_kuerzel is not None and new_kuerzel != old_kuerzel):
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
        ip: str | None,
        request_id: str,
    ) -> PromotionResult:
        """Move all active students from source to target class.

        Uses savepoints per student (same as bulk_add) so partial failures
        don't roll back the whole batch. After the move an optional archive
        of the source class is performed and a single audit event is emitted.
        """
        source = await self.get(source_class_id)
        target = await self.get(target_class_id)
        membership_repo = ClassMembershipRepository(self.session)
        active = await membership_repo.list_for_class(source_class_id, only_active=True)

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
            },
        )
        return PromotionResult(
            students_moved=len(moved),
            students_failed=len(errors),
            errors=errors,
            source_archived=source_archived,
        )
