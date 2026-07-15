"""Admin single-user lifecycle: create a real AD account, or remove a user.

Create provisions an actual AD object (chosen target OU, temp password, forced
change) and immediately mirrors it into ``ad_user_cache`` so it shows up without
waiting for the next sync. Delete is the second step of the two-step lifecycle:
it permanently removes the AD object (Recycle-Bin-recoverable) and the
Magister-side rows, and only accepts an already-disabled account. Both are
admin-only and audited (never the password).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.ad.ou import select_provision_groups
from magister_api.ad.password import generate_password
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.school import School
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.models.user_preferences import UserPreference
from magister_api.repositories.ad_users import AdUserCacheSyncRepository

# Categories offered to the admin. Determine both the target OU and the default
# AD groups. Students are split by Zyklus (1/2/3); the OU still only has two
# student buckets (Zyklus 3 vs the rest), the groups have three.
OU_CHOICES = ("teacher", "student_zyklus1", "student_zyklus2", "student_zyklus3")


class UserAdminError(Exception):
    """Business-rule failure (mapped to a 4xx by the router)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreatedUser:
    ad_object_guid: str
    temp_password: str
    force_change: bool = True


class UserAdminService:
    def __init__(self, session: AsyncSession, settings: Settings, ad: AdClient) -> None:
        self.session = session
        self.settings = settings
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def _provision_target(self, ou_key: str) -> tuple[str, list[str]]:
        """Resolve ``(ou_dn, default_group_dns)`` for a provisioning category."""
        row = (
            await self.session.execute(select(AppSettings).where(AppSettings.id == 1))
        ).scalar_one_or_none()
        if row is None:
            raise UserAdminError("ou_not_configured")
        ou = {
            "teacher": row.ad_ou_teachers,
            "student_zyklus1": row.ad_ou_students_other,
            "student_zyklus2": row.ad_ou_students_other,
            "student_zyklus3": row.ad_ou_students_zyklus3,
        }.get(ou_key)
        if not ou:
            raise UserAdminError("ou_not_configured")
        kind = "teacher" if ou_key == "teacher" else "student"
        zyklus = None if kind == "teacher" else int(ou_key[-1])
        groups = select_provision_groups(
            kind=kind,
            zyklus=zyklus,
            groups_teacher=row.ad_groups_teacher,
            groups_student_zyklus1=row.ad_groups_student_zyklus1,
            groups_student_zyklus2=row.ad_groups_student_zyklus2,
            groups_student_zyklus3=row.ad_groups_student_zyklus3,
        )
        return ou, groups

    async def _school_resolver(self):
        # scope-bypass: provisioning runs as the admin service, not a scoped user.
        schools = list((await self.session.execute(select(School))).scalars().all())

        def _resolve(record: AdUserRecord) -> int | None:
            for s in schools:
                if record.matches_school_via_ou(s.scope_short):
                    return s.id
            return None

        return _resolve

    async def create_user(
        self,
        *,
        given_name: str,
        surname: str,
        sam_account_name: str,
        user_principal_name: str,
        mail: str | None,
        ou_key: str,
        display_name: str | None = None,
        force_change: bool = True,
        cannot_change_password: bool = False,
        password_never_expires: bool = False,
        jahrgangsstufe: int | None = None,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> CreatedUser:
        if ou_key not in OU_CHOICES:
            raise UserAdminError("invalid_ou_choice")
        ou_dn, group_dns = await self._provision_target(ou_key)
        kind = "teacher" if ou_key == "teacher" else "student"
        display = (
            (display_name or "").strip() or f"{given_name} {surname}".strip() or sam_account_name
        )
        password = generate_password()

        guid = await self.ad.create_user(
            ou_dn=ou_dn,
            common_name=display,
            sam_account_name=sam_account_name,
            user_principal_name=user_principal_name,
            mail=mail,
            given_name=given_name,
            surname=surname,
            display_name=display,
            password=password,
            force_change=force_change,
            password_never_expires=password_never_expires,
            cannot_change_password=cannot_change_password,
            group_dns=group_dns,
        )

        record = AdUserRecord(
            ad_object_guid=guid,
            upn=user_principal_name.strip().lower(),
            sam_account_name=sam_account_name,
            given_name=given_name,
            surname=surname,
            display_name=display,
            mail=mail,
            enabled=True,
            kind=kind,
            password_never_expires=password_never_expires,
            ms_ds_consistency_guid=None,
            distinguished_name=f"CN={display},{ou_dn}",
            street_address=None,
            locality=None,
            postal_code=None,
            country=None,
        )
        resolver = await self._school_resolver()
        await AdUserCacheSyncRepository(self.session).upsert_from_ad(
            [record], school_id_resolver=resolver
        )

        # jahrgangsstufe + cannot_change_password are Magister-only fields the
        # sync upsert deliberately does not touch — set them directly on the
        # freshly created cache row (students only for the grade).
        cache = await self.session.get(AdUserCache, guid)
        if cache is not None:
            cache.cannot_change_password = cannot_change_password
            if kind == "student" and jahrgangsstufe is not None:
                cache.jahrgangsstufe = jahrgangsstufe
            await self.session.flush()

        await self.audit.emit(
            action="ad_user_created",
            target_kind="ad_user",
            target_id=guid,
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"kind": kind, "upn": record.upn, "ou_key": ou_key},
        )
        return CreatedUser(ad_object_guid=guid, temp_password=password, force_change=force_change)

    async def delete_user(
        self,
        *,
        ad_object_guid: str,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> bool:
        """Permanently delete a *disabled* user: remove the AD object and the
        Magister rows.

        This is step 2 of the two-step lifecycle — step 1 (deactivate) runs via
        ``PATCH /users/{guid}/status``. Refuses an account that is still enabled
        (``user_not_disabled``). Returns whether an AD object was removed
        (``False`` for a stale cache row with no AD object). With the AD Recycle
        Bin the deletion is recoverable. AD-unavailability / a refused delete
        bubble up as :class:`AdUnavailableError` (router → 503).
        """
        cache = await self.session.get(AdUserCache, ad_object_guid)
        if cache is None:
            raise UserAdminError("user_not_found")
        if cache.enabled:
            # Guard: only deactivated accounts may be permanently deleted.
            raise UserAdminError("user_not_disabled")
        kind = cache.kind
        upn = cache.upn

        # Delete the AD object when it still exists (find_user_dn → None means a
        # stale cache row with nothing left to delete in AD).
        dn = await self.ad.find_user_dn(ad_object_guid)
        ad_removed = False
        if dn is not None:
            await self.ad.delete_user_object(user_dn=dn)
            ad_removed = True

        for stmt in (
            delete(SubjectTeacherRole).where(SubjectTeacherRole.ad_object_guid == ad_object_guid),
            delete(ClassTeacherRole).where(ClassTeacherRole.ad_object_guid == ad_object_guid),
            delete(ClassMembership).where(ClassMembership.ad_object_guid == ad_object_guid),
            delete(RoleAssignment).where(RoleAssignment.ad_object_guid == ad_object_guid),
            delete(UserPreference).where(UserPreference.ad_object_guid == ad_object_guid),
            delete(Session).where(Session.ad_object_guid == ad_object_guid),
        ):
            await self.session.execute(stmt)
        await self.session.delete(cache)
        await self.session.flush()

        await self.audit.emit(
            action="ad_user_deleted",
            target_kind="ad_user",
            target_id=ad_object_guid,
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"kind": kind, "upn": upn, "ad_removed": ad_removed},
        )
        return ad_removed


__all__ = ["OU_CHOICES", "CreatedUser", "UserAdminError", "UserAdminService"]
