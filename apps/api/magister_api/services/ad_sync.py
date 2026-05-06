"""AD-Sync service: pulls users from AD via :class:`AdClient`, upserts ``ad_user_cache``.

The sync is initiated by an Admin via :http:post:`/admin/ad-sync` (M1) and by a
periodic scheduler in the future. Each invocation emits an audit event:

- ``ad_sync_completed`` with ``{synced_count, school_partition}``
- ``ad_sync_failed`` with ``{reason}`` if the AD pool is exhausted or the search throws
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.ad.errors import AdUnavailableError
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.school import School
from magister_api.repositories.ad_users import AdUserCacheSyncRepository


@dataclass(frozen=True)
class SyncResult:
    synced_count: int
    school_partition: dict[int, int]
    """{school_id → count}; key 0 = unmatched (no school)."""


class AdSyncService:
    def __init__(self, session: AsyncSession, settings: Settings, ad: AdClient) -> None:
        self.session = session
        self.settings = settings
        self.ad = ad
        self.repo = AdUserCacheSyncRepository(session)
        self.audit = AuditService(session, settings)

    async def _load_schools(self) -> list[School]:
        # scope-bypass: sync runs as a service user that owns all schools.
        stmt = select(School)
        return list((await self.session.execute(stmt)).scalars().all())

    @staticmethod
    def _school_resolver(schools: list[School]):
        """Return a function ``record -> school_id | None`` driven by ``scope_short`` OU match."""

        def _resolve(record: AdUserRecord) -> int | None:
            for s in schools:
                if record.matches_school_via_ou(s.scope_short):
                    return s.id
            return None

        return _resolve

    async def sync_all(
        self,
        *,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> SyncResult:
        try:
            records = await self.ad.search_users()
        except AdUnavailableError as exc:
            await self.audit.emit(
                action="ad_sync_failed",
                target_kind="ad_sync",
                target_id="all",
                actor_upn=actor_upn,
                actor_object_guid=actor_object_guid,
                school_id=None,
                ip=ip,
                request_id=request_id,
                payload={"reason": str(exc)},
            )
            raise

        schools = await self._load_schools()
        resolver = self._school_resolver(schools)
        partition: dict[int, int] = {}
        for r in records:
            sid = resolver(r) or 0
            partition[sid] = partition.get(sid, 0) + 1
        synced = await self.repo.upsert_from_ad(records, school_id_resolver=resolver)

        await self.audit.emit(
            action="ad_sync_completed",
            target_kind="ad_sync",
            target_id="all",
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={
                "synced_count": synced,
                "school_partition": {str(k): v for k, v in partition.items()},
            },
        )
        return SyncResult(synced_count=synced, school_partition=partition)
