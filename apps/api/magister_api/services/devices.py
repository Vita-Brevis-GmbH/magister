"""DeviceService: orchestrates DeviceRepository + AuditService.

Every mutation emits an audit event (Niemals-Regel: keine schreibende
Operation ohne Audit-Event). Assignment resolves the owning ``school_id``
from the target (person → their school, class → its school, school → itself)
and refuses cross-scope binds for non-admin writers.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.device import Device
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.devices import DeviceRepository


class DeviceNotFoundError(LookupError):
    pass


class DevicePermissionError(PermissionError):
    """Raised on cross-scope assignment attempts."""


class DeviceAssignmentError(ValueError):
    """Raised when the assignment target is missing or invalid."""


class DeviceService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.repo = DeviceRepository(session, scope)
        self.audit = AuditService(session, settings)

    async def list_all(self) -> list[Device]:
        return await self.repo.list_all()

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

        row = await self.repo.set_assignment(
            row,
            school_id=resolved_school,
            class_id=resolved_class,
            assigned_person_guid=resolved_person,
        )
        await self._emit(
            "device_assigned",
            row,
            ip,
            request_id,
            {
                "assignment_type": assignment_type,
                "person_guid": resolved_person,
                "class_id": resolved_class,
            },
        )
        return row

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
]
