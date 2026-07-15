"""Read-side + sync-write repository for ``ad_user_cache``.

Schul-Scope is enforced at the listing layer (every query goes through
:meth:`BaseRepository.apply_scope`). The sync writer ignores scope —
it runs as a service user under :class:`magister_api.services.ad_sync`
which is allowed to bypass with the documented marker.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdUserRecord
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.repositories.base import BaseRepository, ScopeContext


class AdUserListingRepository(BaseRepository):
    """List ad_user_cache rows with filter + pagination, scoped to the user's schools."""

    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    async def list_filtered(
        self,
        *,
        kind: str | None = None,
        enabled: bool | None = None,
        search: str | None = None,
        class_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AdUserCache], int]:
        """Return ``(rows, total_count)`` with all filters applied."""
        stmt = self.apply_scope(select(AdUserCache), AdUserCache.school_id)
        count_stmt = self.apply_scope(
            select(func.count()).select_from(AdUserCache), AdUserCache.school_id
        )
        if kind is not None:
            stmt = stmt.where(AdUserCache.kind == kind)
            count_stmt = count_stmt.where(AdUserCache.kind == kind)
        if enabled is not None:
            stmt = stmt.where(AdUserCache.enabled == enabled)
            count_stmt = count_stmt.where(AdUserCache.enabled == enabled)
        if search:
            pattern = f"%{search.lower()}%"
            search_pred = or_(
                func.lower(AdUserCache.upn).like(pattern),
                func.lower(AdUserCache.given_name).like(pattern),
                func.lower(AdUserCache.surname).like(pattern),
            )
            stmt = stmt.where(search_pred)
            count_stmt = count_stmt.where(search_pred)
        if class_id is not None:
            # Limit to users with an active class_teacher_roles row (teachers)
            # OR an active class_memberships row (students) for this class, so
            # the class filter surfaces both sides of the class.
            from magister_api.models.base import utcnow as _now

            ts = _now()
            kl_subq = (
                select(ClassTeacherRole.ad_object_guid)
                .where(ClassTeacherRole.class_id == class_id)
                .where(ClassTeacherRole.valid_from <= ts)
                .where((ClassTeacherRole.valid_to.is_(None)) | (ClassTeacherRole.valid_to > ts))
            )
            member_subq = (
                select(ClassMembership.ad_object_guid)
                .where(ClassMembership.class_id == class_id)
                .where(ClassMembership.valid_from <= ts)
                .where((ClassMembership.valid_to.is_(None)) | (ClassMembership.valid_to > ts))
            )
            class_pred = or_(
                AdUserCache.ad_object_guid.in_(kl_subq),
                AdUserCache.ad_object_guid.in_(member_subq),
            )
            stmt = stmt.where(class_pred)
            count_stmt = count_stmt.where(class_pred)
        stmt = (
            stmt.order_by(AdUserCache.surname, AdUserCache.given_name, AdUserCache.upn)
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def latest_sync_for_scope(self) -> datetime | None:
        """Most recent ``last_sync_at`` across the user's school scope."""
        stmt = self.apply_scope(select(func.max(AdUserCache.last_sync_at)), AdUserCache.school_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class AdUserCacheSyncRepository:
    """Write-side repo used by the sync service. NOT scope-filtered.

    # scope-bypass: AD sync runs as a service user that owns all schools by definition.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_from_ad(
        self,
        records: Sequence[AdUserRecord],
        *,
        school_id_resolver: Callable[[AdUserRecord], int | None],
    ) -> int:
        """Upsert each record. ``school_id_resolver(record) -> int | None``."""
        if not records:
            return 0
        now = utcnow()
        rows: list[dict[str, Any]] = []
        for r in records:
            rows.append(
                {
                    "ad_object_guid": r.ad_object_guid,
                    "school_id": school_id_resolver(r),
                    "upn": r.upn,
                    "sam_account_name": r.sam_account_name,
                    "given_name": r.given_name,
                    "surname": r.surname,
                    "display_name": r.display_name,
                    "mail": r.mail,
                    "kind": r.kind,
                    "enabled": r.enabled,
                    "last_sync_at": now,
                    "ms_ds_consistency_guid": r.ms_ds_consistency_guid,
                    "street_address": r.street_address,
                    "locality": r.locality,
                    "postal_code": r.postal_code,
                    "country": r.country,
                    "device_name": r.device_name,
                    "password_never_expires": r.password_never_expires,
                    "ad_groups": list(r.groups),
                    # temp_device_name, jahrgangsstufe and cannot_change_password
                    # are Magister-only — do NOT overwrite on AD sync. We omit
                    # them from both VALUES and the ON-CONFLICT set; existing
                    # rows keep whatever was set via the PATCH-user endpoint.
                    # (cannot_change_password lives in the object's DACL, which
                    # the sync does not read back.)
                }
            )
        stmt = (
            pg_insert(AdUserCache)
            .values(rows)
            .on_conflict_do_update(
                index_elements=[AdUserCache.ad_object_guid],
                set_={
                    "school_id": pg_insert(AdUserCache).excluded.school_id,
                    "upn": pg_insert(AdUserCache).excluded.upn,
                    "sam_account_name": pg_insert(AdUserCache).excluded.sam_account_name,
                    "given_name": pg_insert(AdUserCache).excluded.given_name,
                    "surname": pg_insert(AdUserCache).excluded.surname,
                    "display_name": pg_insert(AdUserCache).excluded.display_name,
                    "mail": pg_insert(AdUserCache).excluded.mail,
                    "kind": pg_insert(AdUserCache).excluded.kind,
                    "enabled": pg_insert(AdUserCache).excluded.enabled,
                    "last_sync_at": now,
                    "ms_ds_consistency_guid": pg_insert(
                        AdUserCache
                    ).excluded.ms_ds_consistency_guid,
                    "street_address": pg_insert(AdUserCache).excluded.street_address,
                    "locality": pg_insert(AdUserCache).excluded.locality,
                    "postal_code": pg_insert(AdUserCache).excluded.postal_code,
                    "country": pg_insert(AdUserCache).excluded.country,
                    "device_name": pg_insert(AdUserCache).excluded.device_name,
                    "password_never_expires": pg_insert(
                        AdUserCache
                    ).excluded.password_never_expires,
                    "ad_groups": pg_insert(AdUserCache).excluded.ad_groups,
                },
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return len(rows)
