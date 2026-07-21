"""AD-Sync service: pulls users from AD via :class:`AdClient`, upserts ``ad_user_cache``.

The sync is initiated by an Admin via :http:post:`/admin/ad-sync` and by the
periodic scheduler (:mod:`magister_api.services.ad_sync_scheduler`). Each
invocation emits an audit event:

- ``ad_sync_completed`` with ``{mode, synced_count, school_partition, cursor_before, cursor_after}``
- ``ad_sync_failed`` with ``{reason, mode}`` if the AD pool is exhausted or the search throws

Two modes:

- ``full`` — search all users, run the Computer-OU walk, reset the cursor
- ``incremental`` — narrow LDAP filter to ``whenChanged >= last_cursor``,
  skip the Computer-OU walk (refreshed on the next full sync). Cannot
  detect deletions; the scheduler must trigger a full sync periodically.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient, AdUserRecord, classify_kind_by_ou
from magister_api.ad.errors import AdUnavailableError
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.ad_group import AdGroupCache
from magister_api.models.ad_sync_state import AdSyncState
from magister_api.models.app_settings import AppSettings
from magister_api.models.device import Device
from magister_api.models.school import School
from magister_api.repositories.ad_groups import AdGroupCatalogRepository
from magister_api.repositories.ad_users import AdUserCacheSyncRepository
from magister_api.services.devices import import_devices_from_ad

SyncMode = Literal["full", "incremental"]


@dataclass(frozen=True)
class SyncResult:
    synced_count: int
    school_partition: dict[int, int]
    """{school_id → count}; key 0 = unmatched (no school)."""
    device_count: int = 0
    """Number of users that received a device_name from the Computer-OU walk."""
    devices_imported: int = 0
    """Number of Computer objects upserted into the device inventory."""
    group_count: int = 0
    """Number of AD groups mirrored into the group catalog."""
    mode: SyncMode = "full"
    cursor_before: datetime | None = None
    cursor_after: datetime | None = None


class AdSyncService:
    def __init__(self, session: AsyncSession, settings: Settings, ad: AdClient) -> None:
        self.session = session
        self.settings = settings
        self.ad = ad
        self.repo = AdUserCacheSyncRepository(session)
        self.audit = AuditService(session, settings)

    async def _reclassify_by_ou(self, records: list[AdUserRecord]) -> list[AdUserRecord]:
        """Override each record's ``kind`` from the per-school target OUs.

        The per-school provisioning OUs are the authority for teacher-vs-student:
        a DN under any school's teacher OU is a teacher, under any student OU a
        student. Falls back to the AD-group guess already on the record when the
        DN matches no configured OU. Uses the UNION of all schools' OUs so a user
        under any Schulhaus classifies correctly.

        # scope-bypass: sync runs as a service user that owns all schools.
        """
        schools = await self._load_schools()
        teacher_ous = [s.ad_ou_teachers for s in schools if s.ad_ou_teachers]
        student_ous = [
            ou for s in schools for ou in (s.ad_ou_students_zyklus3, s.ad_ou_students_other) if ou
        ]
        if not teacher_ous and not student_ous:
            # No target OUs configured on any school — keep group-based guess.
            return records
        return [
            replace(
                r,
                kind=classify_kind_by_ou(
                    r.distinguished_name,
                    r.kind,
                    teacher_ous=teacher_ous,
                    student_ous=student_ous,
                ),
            )
            for r in records
        ]

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

    async def _load_state(self) -> AdSyncState:
        existing = await self.session.get(AdSyncState, 1)
        if existing is not None:
            return existing
        state = AdSyncState(id=1)
        self.session.add(state)
        await self.session.flush()
        return state

    async def _sync_group_catalog(self) -> int:
        """Refresh ``ad_group_cache`` from AD. Returns the number of groups seen.

        # scope-bypass: AD groups are global (no school scope).
        """
        row = (
            await self.session.execute(
                select(
                    AppSettings.ad_groups_search_base,
                    AppSettings.ad_users_search_base,
                ).where(AppSettings.id == 1)
            )
        ).one_or_none()
        base = None
        if row is not None:
            base = row.ad_groups_search_base or row.ad_users_search_base
        groups = await self.ad.search_groups(search_base=base)
        if not groups:
            return 0
        return await AdGroupCatalogRepository(self.session).upsert_from_ad(groups)

    async def sync_all(
        self,
        *,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
        mode: SyncMode = "full",
    ) -> SyncResult:
        state = await self._load_state()
        cursor_before = state.last_when_changed
        # If incremental was requested but we have no cursor yet, fall back to full.
        effective_mode: SyncMode = (
            "full" if mode == "full" or cursor_before is None else "incremental"
        )

        try:
            records = await self.ad.search_users(
                changed_since=cursor_before if effective_mode == "incremental" else None
            )
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
                payload={"reason": str(exc), "mode": effective_mode},
            )
            raise

        records = await self._reclassify_by_ou(records)

        schools = await self._load_schools()
        resolver = self._school_resolver(schools)
        partition: dict[int, int] = {}
        for r in records:
            sid = resolver(r) or 0
            partition[sid] = partition.get(sid, 0) + 1

        # Computer-OU walk is full-sync only — device assignments don't move
        # often and a stale device_name on a delta-changed user is acceptable
        # until the next full sync runs.
        device_count = 0
        devices_imported = 0
        groups_imported = 0
        device_total = 0
        group_total = 0
        if effective_mode == "full":
            device_map = await self.ad.search_managed_computers()
            if device_map:
                records = [
                    replace(r, device_name=device_map.get(r.distinguished_name.lower()))
                    for r in records
                ]
            device_count = sum(1 for r in records if r.device_name)

            # Import the whole Computer-OU into the Magister-managed devices
            # table by name+objectGUID. Bindings to persons/classes/schools are
            # owned by Magister, not AD, so this only upserts the inventory.
            computers = await self.ad.search_computers()
            if computers:
                devices_imported = await import_devices_from_ad(self.session, computers)

            # Group catalog (Userkonfiguration checkbox-picker). Full-sync only;
            # a wrong/empty base is a soft-no-op inside search_groups().
            groups_imported = await self._sync_group_catalog()

            # Report the *inventory totals* to the operator (not "created this
            # run"), so "N Geräte / M Gruppen" matches what the device list and
            # the group picker actually show.
            device_total = int(
                (await self.session.execute(select(func.count()).select_from(Device))).scalar_one()
            )
            group_total = int(
                (
                    await self.session.execute(select(func.count()).select_from(AdGroupCache))
                ).scalar_one()
            )

        synced = await self.repo.upsert_from_ad(records, school_id_resolver=resolver)

        cursor_after = max(
            (r.when_changed for r in records if r.when_changed is not None),
            default=cursor_before,
        )
        now = datetime.now(UTC)
        state.last_when_changed = cursor_after
        state.last_synced_count = synced
        state.last_mode = effective_mode
        if effective_mode == "full":
            state.last_full_sync_at = now

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
                "mode": effective_mode,
                "synced_count": synced,
                "device_count": device_count,
                "devices_imported": devices_imported,
                "groups_imported": groups_imported,
                "school_partition": {str(k): v for k, v in partition.items()},
                "cursor_before": cursor_before.isoformat() if cursor_before else None,
                "cursor_after": cursor_after.isoformat() if cursor_after else None,
            },
        )
        return SyncResult(
            synced_count=synced,
            school_partition=partition,
            device_count=device_count,
            # UI-facing counts are the inventory/catalog totals (see above), so
            # they match the device list and group picker; the audit payload
            # keeps the "created this run" figures.
            devices_imported=device_total,
            group_count=group_total,
            mode=effective_mode,
            cursor_before=cursor_before,
            cursor_after=cursor_after,
        )
