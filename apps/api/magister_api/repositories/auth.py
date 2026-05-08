"""Repositories for sessions, role assignments, AD-user-cache lookups."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.base import utcnow


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        session_id: str,
        ad_object_guid: str,
        oidc_subject: str,
        lifetime: timedelta,
        ip: str | None,
        user_agent: str | None,
        auth_kind: str = "oidc",
    ) -> Session:
        now = utcnow()
        row = Session(
            id=session_id,
            ad_object_guid=ad_object_guid,
            oidc_subject=oidc_subject,
            auth_kind=auth_kind,
            expires_at=now + lifetime,
            last_seen_at=now,
            ip=ip,
            user_agent=user_agent,
            created_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, session_id: str) -> Session | None:
        return await self.session.get(Session, session_id)

    async def touch(self, session_id: str, lifetime: timedelta) -> Session | None:
        row = await self.get(session_id)
        if row is None:
            return None
        now = utcnow()
        row.last_seen_at = now
        row.expires_at = now + lifetime
        await self.session.flush()
        return row

    async def delete(self, session_id: str) -> None:
        row = await self.get(session_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()


class RoleAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_for(self, ad_object_guid: str) -> list[RoleAssignment]:
        stmt = select(RoleAssignment).where(
            and_(
                RoleAssignment.ad_object_guid == ad_object_guid,
                RoleAssignment.revoked_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def grant(
        self,
        *,
        ad_object_guid: str,
        role: str,
        school_id: int | None,
        granted_by: str | None,
    ) -> RoleAssignment:
        existing = await self._find_active(ad_object_guid, role, school_id)
        if existing is not None:
            return existing
        row = RoleAssignment(
            ad_object_guid=ad_object_guid,
            role=role,
            school_id=school_id,
            granted_by=granted_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def revoke(
        self,
        *,
        ad_object_guid: str,
        role: str,
        school_id: int | None,
    ) -> RoleAssignment | None:
        row = await self._find_active(ad_object_guid, role, school_id)
        if row is None:
            return None
        row.revoked_at = datetime.now(UTC)
        await self.session.flush()
        return row

    async def _find_active(
        self, ad_object_guid: str, role: str, school_id: int | None
    ) -> RoleAssignment | None:
        cond = and_(
            RoleAssignment.ad_object_guid == ad_object_guid,
            RoleAssignment.role == role,
            RoleAssignment.revoked_at.is_(None),
        )
        if school_id is None:
            cond = and_(cond, RoleAssignment.school_id.is_(None))
        else:
            cond = and_(cond, RoleAssignment.school_id == school_id)
        result = await self.session.execute(select(RoleAssignment).where(cond))
        return result.scalar_one_or_none()


class AdUserCacheRepository:
    """Read-mostly repository — population is owned by the AD sync (issue #3)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_oidc_subject(self, *, oid: str | None, upn: str) -> AdUserCache | None:
        """Match OIDC `oid` against ms-DS-ConsistencyGuid; UPN fallback."""
        conditions = []
        if oid:
            conditions.append(AdUserCache.ms_ds_consistency_guid == oid.lower())
        conditions.append(AdUserCache.upn == upn.lower())
        stmt = select(AdUserCache).where(or_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert_admin(
        self,
        *,
        ad_object_guid: str,
        upn: str,
        ms_ds_consistency_guid: str | None,
    ) -> AdUserCache:
        """Bootstrap-only path — used to seed an admin's cache row on first login.

        # scope-bypass: bootstrap admin has school_id=NULL by design (cross-school).
        """
        stmt = (
            pg_insert(AdUserCache)
            .values(
                ad_object_guid=ad_object_guid,
                school_id=None,
                upn=upn,
                kind="admin",
                enabled=True,
                last_sync_at=None,
                ms_ds_consistency_guid=ms_ds_consistency_guid,
            )
            .on_conflict_do_update(
                index_elements=[AdUserCache.ad_object_guid],
                set_={
                    "upn": upn,
                    "ms_ds_consistency_guid": ms_ds_consistency_guid,
                    "kind": "admin",
                    "enabled": True,
                },
            )
            .returning(AdUserCache)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one()
        await self.session.flush()
        return row
