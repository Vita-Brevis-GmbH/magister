"""Admin single-user lifecycle: create a real AD account, or remove a user.

Create provisions an actual AD object (chosen target OU, temp password, forced
change) and immediately mirrors it into ``ad_user_cache`` so it shows up without
waiting for the next sync. Delete disables the AD account and removes the
Magister-side rows. Both are admin-only and audited (never the password).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient, AdUserRecord
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

# OU choices offered to the admin, mapped to the configured provisioning OUs.
OU_CHOICES = ("teacher", "student_zyklus3", "student_other")


class UserAdminError(Exception):
    """Business-rule failure (mapped to a 4xx by the router)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreatedUser:
    ad_object_guid: str
    temp_password: str


class UserAdminService:
    def __init__(self, session: AsyncSession, settings: Settings, ad: AdClient) -> None:
        self.session = session
        self.settings = settings
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def _target_ou(self, ou_key: str) -> str:
        row = (
            await self.session.execute(
                select(
                    AppSettings.ad_ou_teachers,
                    AppSettings.ad_ou_students_zyklus3,
                    AppSettings.ad_ou_students_other,
                ).where(AppSettings.id == 1)
            )
        ).one_or_none()
        ou = None
        if row is not None:
            ou = {
                "teacher": row.ad_ou_teachers,
                "student_zyklus3": row.ad_ou_students_zyklus3,
                "student_other": row.ad_ou_students_other,
            }.get(ou_key)
        if not ou:
            raise UserAdminError("ou_not_configured")
        return ou

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
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> CreatedUser:
        if ou_key not in OU_CHOICES:
            raise UserAdminError("invalid_ou_choice")
        ou_dn = await self._target_ou(ou_key)
        kind = "teacher" if ou_key == "teacher" else "student"
        display_name = f"{given_name} {surname}".strip() or sam_account_name
        password = generate_password()

        guid = await self.ad.create_user(
            ou_dn=ou_dn,
            common_name=display_name,
            sam_account_name=sam_account_name,
            user_principal_name=user_principal_name,
            mail=mail,
            given_name=given_name,
            surname=surname,
            display_name=display_name,
            password=password,
            force_change=True,
        )

        record = AdUserRecord(
            ad_object_guid=guid,
            upn=user_principal_name.strip().lower(),
            sam_account_name=sam_account_name,
            given_name=given_name,
            surname=surname,
            display_name=display_name,
            mail=mail,
            enabled=True,
            kind=kind,
            password_never_expires=False,
            ms_ds_consistency_guid=None,
            distinguished_name=f"CN={display_name},{ou_dn}",
            street_address=None,
            locality=None,
            postal_code=None,
            country=None,
        )
        resolver = await self._school_resolver()
        await AdUserCacheSyncRepository(self.session).upsert_from_ad(
            [record], school_id_resolver=resolver
        )

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
        return CreatedUser(ad_object_guid=guid, temp_password=password)

    async def delete_user(
        self,
        *,
        ad_object_guid: str,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> bool:
        """Disable the AD account (if present) and remove the Magister rows.

        Returns whether an AD account was disabled. Raises ``UserAdminError``
        if the user is unknown; AD-unavailability bubbles up as
        :class:`AdUnavailableError` (the router maps it to 503).
        """
        cache = await self.session.get(AdUserCache, ad_object_guid)
        if cache is None:
            raise UserAdminError("user_not_found")
        kind = cache.kind
        upn = cache.upn

        # Disable in AD when the object still exists (find_user_dn → None means
        # there is nothing to disable, e.g. a stale cache row).
        dn = await self.ad.find_user_dn(ad_object_guid)
        ad_disabled = False
        if dn is not None:
            await self.ad.set_account_enabled(user_dn=dn, enabled=False)
            ad_disabled = True

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
            payload={"kind": kind, "upn": upn, "ad_disabled": ad_disabled},
        )
        return ad_disabled


__all__ = ["OU_CHOICES", "CreatedUser", "UserAdminError", "UserAdminService"]
