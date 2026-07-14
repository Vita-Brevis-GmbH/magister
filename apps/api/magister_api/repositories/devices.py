"""Device repository.

Devices are school-scoped for RBAC, with one deliberate widening: the *free
pool* (``school_id IS NULL``) is visible to every writer (Admin and SMI) so an
unassigned device can be picked up and bound to a school/class/person. Admin
sees everything; a scoped SMI sees their schools' devices plus the free pool.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.device import DEVICE_SOURCE_AD, DEVICE_SOURCE_MANUAL, Device
from magister_api.repositories.base import BaseRepository, ScopeContext


class DeviceRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    def _visible(self, stmt):  # type: ignore[no-untyped-def]
        """Restrict a Device select to what the caller may see.

        Admin: everything. Otherwise: rows in the caller's school scope plus
        the free pool (``school_id IS NULL``). This is intentionally wider
        than ``apply_scope`` (which would hide the free pool), so the OR-NULL
        is spelled out here rather than bypassed silently.
        """
        if self.scope.is_admin:
            return stmt
        if not self.scope.school_scope:
            return stmt.where(Device.school_id.is_(None))
        return stmt.where(
            or_(
                Device.school_id.in_(self.scope.school_scope),
                Device.school_id.is_(None),
            )
        )

    async def list_all(self) -> list[Device]:
        stmt = self._visible(select(Device)).order_by(Device.name, Device.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, device_id: int) -> Device | None:
        stmt = self._visible(select(Device).where(Device.id == device_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_person(self, ad_object_guid: str) -> list[Device]:
        """Devices assigned to one person (by AD objectGUID), scope-restricted."""
        stmt = self._visible(
            select(Device).where(Device.assigned_person_guid == ad_object_guid)
        ).order_by(Device.name, Device.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        name: str,
        device_type: str | None,
        serial_number: str | None,
        notes: str | None,
    ) -> Device:
        row = Device(
            name=name,
            device_type=device_type,
            serial_number=serial_number,
            notes=notes,
            source=DEVICE_SOURCE_MANUAL,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self,
        device: Device,
        *,
        name: str | None = None,
        device_type: str | None = None,
        serial_number: str | None = None,
        notes: str | None = None,
    ) -> Device:
        if name is not None and name != device.name:
            device.name = name
        if device_type is not None:
            device.device_type = device_type
        if serial_number is not None:
            device.serial_number = serial_number
        if notes is not None:
            device.notes = notes
        await self.session.flush()
        return device

    async def set_assignment(
        self,
        device: Device,
        *,
        school_id: int | None,
        class_id: int | None,
        assigned_person_guid: str | None,
    ) -> Device:
        device.school_id = school_id
        device.class_id = class_id
        device.assigned_person_guid = assigned_person_guid
        await self.session.flush()
        return device

    async def delete(self, device: Device) -> None:
        await self.session.delete(device)
        await self.session.flush()

    async def upsert_from_ad(self, computers: list[tuple[str, str]]) -> int:
        """Import AD computer objects as devices, keyed on ``ad_object_guid``.

        ``computers`` is a list of ``(object_guid, name)``. Existing rows keep
        their Magister-managed attributes and bindings; only the *name* is
        refreshed from AD. Unknown GUIDs are inserted as free devices. Returns
        the number of rows created.

        Runs unscoped by design — the importer is a system-level full-AD walk,
        not a per-user request.
        """
        # scope-bypass: system AD import walks the whole Computer-OU; the
        # resulting devices start in the free pool (school_id NULL) and are
        # bound to a school/class/person by a scoped writer afterwards.
        if not computers:
            return 0
        guids = [g for g, _ in computers]
        existing = {
            d.ad_object_guid: d
            for d in (
                await self.session.execute(select(Device).where(Device.ad_object_guid.in_(guids)))
            )
            .scalars()
            .all()
        }
        created = 0
        for guid, name in computers:
            row = existing.get(guid)
            if row is None:
                self.session.add(
                    Device(
                        name=name,
                        ad_object_guid=guid,
                        source=DEVICE_SOURCE_AD,
                    )
                )
                created += 1
            elif name and name != row.name:
                row.name = name
        await self.session.flush()
        return created
