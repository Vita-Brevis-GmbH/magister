"""DeviceService: orchestrates DeviceRepository + AuditService.

Every mutation emits an audit event (Niemals-Regel: keine schreibende
Operation ohne Audit-Event). Assignment resolves the owning ``school_id``
from the target (person → their school, class → its school, school → itself)
and refuses cross-scope binds for non-admin writers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy import update as sqla_update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.device import Device
from magister_api.models.device_assignment import DeviceAssignment
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.devices import DeviceRepository


class DeviceNotFoundError(LookupError):
    pass


class DevicePermissionError(PermissionError):
    """Raised on cross-scope assignment attempts."""


class DeviceAssignmentError(ValueError):
    """Raised when the assignment target is missing or invalid."""


def _assignee_key(device: Device) -> tuple[str, object, bool] | None:
    """Identity of a device's current holder (type, id, is_loan), or None if free.

    Person takes precedence over class over school (a person-assigned device
    also carries the derived school_id). The loaner flag is part of the key so a
    fixed↔loaner flip is recorded as a new history period.
    """
    if device.assigned_person_guid:
        return ("person", device.assigned_person_guid, device.is_loan)
    if device.class_id is not None:
        return ("class", device.class_id, False)
    if device.school_id is not None:
        return ("school", device.school_id, False)
    return None


class DeviceService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = DeviceRepository(session, scope)
        self.audit = AuditService(session, settings)

    async def list_all(self) -> list[Device]:
        return await self.repo.list_all()

    async def person_names(self, guids: set[str]) -> dict[str, str]:
        """Map ``objectGUID → display label`` for assigned persons.

        Display-only resolution so the device UI shows a name, not a GUID.

        # scope-bypass: the device rows are already scope-authorized; this only
        # reads the assignee's label (display_name / name / UPN) for rendering.
        """
        clean = {g for g in guids if g}
        if not clean:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(AdUserCache).where(AdUserCache.ad_object_guid.in_(clean))
                )
            )
            .scalars()
            .all()
        )
        out: dict[str, str] = {}
        for u in rows:
            label = (
                u.display_name
                or f"{u.given_name or ''} {u.surname or ''}".strip()
                or u.upn
                or u.ad_object_guid
            )
            out[u.ad_object_guid] = label
        return out

    async def get(self, device_id: int) -> Device:
        row = await self.repo.get(device_id)
        if row is None:
            raise DeviceNotFoundError(str(device_id))
        return row

    async def create(
        self,
        *,
        name: str,
        device_type: str | None,
        serial_number: str | None,
        notes: str | None,
        ip: str | None,
        request_id: str,
    ) -> Device:
        row = await self.repo.create(
            name=name,
            device_type=device_type,
            serial_number=serial_number,
            notes=notes,
        )
        await self._emit("device_created", row, ip, request_id, {"name": row.name})
        return row

    async def update(
        self,
        *,
        device_id: int,
        name: str | None,
        device_type: str | None,
        serial_number: str | None,
        notes: str | None,
        ip: str | None,
        request_id: str,
    ) -> Device:
        row = await self.get(device_id)
        old_name = row.name
        row = await self.repo.update(
            row,
            name=name,
            device_type=device_type,
            serial_number=serial_number,
            notes=notes,
        )
        await self._emit(
            "device_updated",
            row,
            ip,
            request_id,
            {"old_name": old_name, "new_name": row.name},
        )
        return row

    async def delete(self, *, device_id: int, ip: str | None, request_id: str) -> None:
        row = await self.get(device_id)
        payload = {"name": row.name, "source": row.source}
        school_id = row.school_id
        await self.repo.delete(row)
        await self.audit.emit(
            action="device_deleted",
            target_kind="device",
            target_id=str(device_id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=school_id,
            ip=ip,
            request_id=request_id,
            payload=payload,
        )

    async def assign(
        self,
        *,
        device_id: int,
        assignment_type: str,
        person_guid: str | None,
        class_id: int | None,
        school_id: int | None,
        is_loan: bool = False,
        ip: str | None,
        request_id: str,
    ) -> Device:
        row = await self.get(device_id)
        resolved_school, resolved_class, resolved_person = await self._resolve_target(
            assignment_type=assignment_type,
            person_guid=person_guid,
            class_id=class_id,
            school_id=school_id,
        )
        # Non-admin writers may only bind into a school they scope. Free is
        # always allowed (unbinding / returning to the pool).
        if resolved_school is not None and not self.scope.can_access_school(resolved_school):
            raise DevicePermissionError("school_out_of_scope")

        old_key = _assignee_key(row)
        row = await self.repo.set_assignment(
            row,
            school_id=resolved_school,
            class_id=resolved_class,
            assigned_person_guid=resolved_person,
            is_loan=is_loan,
        )
        await self._record_history_transition(row, old_key)
        await self._emit(
            "device_assigned",
            row,
            ip,
            request_id,
            {
                "assignment_type": assignment_type,
                "person_guid": resolved_person,
                "class_id": resolved_class,
                "is_loan": row.is_loan,
            },
        )
        return row

    async def _record_history_transition(
        self, device: Device, old_key: tuple[str, object, bool] | None
    ) -> None:
        """Close the open history row and open a new one when the holder changed.

        No-op when the assignment (holder + loaner flag) is unchanged.
        """
        new_key = _assignee_key(device)
        if old_key == new_key:
            return
        now = utcnow()
        if old_key is not None:
            await self._close_open_history(device.id, now)
        if new_key is not None:
            label = await self._assignee_label(device)
            self.session.add(
                DeviceAssignment(
                    device_id=device.id,
                    assignment_type=str(new_key[0]),
                    assigned_person_guid=device.assigned_person_guid,
                    class_id=device.class_id if new_key[0] == "class" else None,
                    school_id=device.school_id if new_key[0] == "school" else None,
                    label=label,
                    is_loan=device.is_loan,
                    valid_from=now,
                    valid_to=None,
                )
            )
            await self.session.flush()

    async def _close_open_history(self, device_id: int, end_at: datetime) -> None:
        await self.session.execute(
            sqla_update(DeviceAssignment)
            .where(DeviceAssignment.device_id == device_id, DeviceAssignment.valid_to.is_(None))
            .values(valid_to=end_at)
        )

    async def _assignee_label(self, device: Device) -> str:
        """Snapshot the current holder's display label for the history row."""
        if device.assigned_person_guid:
            names = await self.person_names({device.assigned_person_guid})
            return names.get(device.assigned_person_guid, device.assigned_person_guid)
        if device.class_id is not None:
            cls = await self.session.get(SchoolClass, device.class_id)
            return cls.name if cls else str(device.class_id)
        if device.school_id is not None:
            school = await self.session.get(School, device.school_id)
            return school.name if school else str(device.school_id)
        return ""

    async def history(self, device_id: int) -> list[DeviceAssignment]:
        """Full assignment history for a device, newest first."""
        await self.get(device_id)  # scope check / 404
        rows = (
            await self.session.execute(
                select(DeviceAssignment)
                .where(DeviceAssignment.device_id == device_id)
                .order_by(DeviceAssignment.valid_from.desc(), DeviceAssignment.id.desc())
            )
        ).scalars()
        return list(rows.all())

    async def _resolve_target(
        self,
        *,
        assignment_type: str,
        person_guid: str | None,
        class_id: int | None,
        school_id: int | None,
    ) -> tuple[int | None, int | None, str | None]:
        """Return ``(school_id, class_id, person_guid)`` for the assignment."""
        if assignment_type == "free":
            return None, None, None

        if assignment_type == "person":
            if not person_guid:
                raise DeviceAssignmentError("person_guid_required")
            # scope-bypass: we only read the target's school_id to derive the
            # device's scope; the caller's own scope is enforced afterwards.
            person = await self.session.get(AdUserCache, person_guid)
            if person is None:
                raise DeviceAssignmentError("person_not_found")
            return person.school_id, None, person_guid

        if assignment_type == "class":
            if class_id is None:
                raise DeviceAssignmentError("class_id_required")
            # scope-bypass: same as above — the class's school_id is the
            # device scope; the caller's scope gate runs on the result.
            cls = await self.session.get(SchoolClass, class_id)
            if cls is None:
                raise DeviceAssignmentError("class_not_found")
            return cls.school_id, class_id, None

        if assignment_type == "school":
            if school_id is None:
                raise DeviceAssignmentError("school_id_required")
            return school_id, None, None

        raise DeviceAssignmentError("invalid_assignment_type")

    async def _emit(
        self,
        action: str,
        row: Device,
        ip: str | None,
        request_id: str,
        payload: dict[str, object],
    ) -> None:
        await self.audit.emit(
            action=action,
            target_kind="device",
            target_id=str(row.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=row.school_id,
            ip=ip,
            request_id=request_id,
            payload=payload,
        )


async def release_person_devices(
    session: AsyncSession,
    settings: Settings,
    ad_object_guid: str,
    *,
    actor_upn: str,
    actor_object_guid: str | None,
    ip: str | None,
    request_id: str,
) -> int:
    """Free every device assigned to a person and close its open history row.

    Called when a user is deleted so their devices return to the free pool
    instead of staying stuck on a now-gone objectGUID. Returns the count freed.

    # scope-bypass: the caller (admin user-delete) is already authorized; this
    # releases the person's devices regardless of school so none are orphaned.
    """
    devices = list(
        (await session.execute(select(Device).where(Device.assigned_person_guid == ad_object_guid)))
        .scalars()
        .all()
    )
    if not devices:
        return 0
    audit = AuditService(session, settings)
    now = utcnow()
    for d in devices:
        await session.execute(
            sqla_update(DeviceAssignment)
            .where(DeviceAssignment.device_id == d.id, DeviceAssignment.valid_to.is_(None))
            .values(valid_to=now)
        )
        prev_school = d.school_id
        d.school_id = None
        d.class_id = None
        d.assigned_person_guid = None
        d.is_loan = False
        await audit.emit(
            action="device_released",
            target_kind="device",
            target_id=str(d.id),
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=prev_school,
            ip=ip,
            request_id=request_id,
            payload={"reason": "user_deleted", "person_guid": ad_object_guid},
        )
    await session.flush()
    return len(devices)


async def import_devices_from_ad(
    session: AsyncSession,
    computers: list[tuple[str, str]],
) -> int:
    """Upsert AD computer objects into the devices table (system context).

    Returns the number of newly created device rows. Used by the AD sync.
    """
    repo = DeviceRepository(session, _system_scope())
    return await repo.upsert_from_ad(computers)


def _system_scope() -> ScopeContext:
    """Admin-equivalent scope for the AD import job (no HTTP user)."""
    return ScopeContext(ad_object_guid="", upn="system:ad-sync", is_admin=True)


__all__ = [
    "DeviceAssignmentError",
    "DeviceNotFoundError",
    "DevicePermissionError",
    "DeviceService",
    "import_devices_from_ad",
    "release_person_devices",
]
