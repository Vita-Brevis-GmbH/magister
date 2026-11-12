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
from magister_api.ad.ou import ou_within_school, select_provision_groups
from magister_api.ad.password import default_profile_for_kind, generate_for_profile
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.group_template import FIXED_KINDS, GroupTemplate
from magister_api.models.school import School
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.models.user_preferences import UserPreference
from magister_api.repositories.ad_users import AdUserCacheSyncRepository
from magister_api.repositories.group_templates import GroupTemplateRepository
from magister_api.services.devices import release_person_devices
from magister_api.services.password_vault import PasswordVaultService, password_stays

# Categories offered to the admin. Determine both the target OU and the default
# AD groups. Students are split by Zyklus (1/2/3); the OU still only has two
# student buckets (Zyklus 3 vs the rest), the groups have three. The company
# edition provisions a single "company" category into the org unit's company OU.
OU_CHOICES = ("teacher", "student_zyklus1", "student_zyklus2", "student_zyklus3", "company")


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

    async def _provision_target(self, ou_key: str, school: School) -> tuple[str, list[str]]:
        """Resolve ``(ou_dn, default_group_dns)`` for a provisioning category.

        OUs + group templates come from the target school (per-school config).
        """
        if ou_key == "company":
            # Company edition: one flat target OU + the org unit's company groups.
            if not school.ad_ou_company_users:
                raise UserAdminError("ou_not_configured")
            return school.ad_ou_company_users, list(school.ad_groups_company or [])
        ou = {
            "teacher": school.ad_ou_teachers,
            "student_zyklus1": school.ad_ou_students_other,
            "student_zyklus2": school.ad_ou_students_other,
            "student_zyklus3": school.ad_ou_students_zyklus3,
        }.get(ou_key)
        if not ou:
            raise UserAdminError("ou_not_configured")
        kind = "teacher" if ou_key == "teacher" else "student"
        zyklus = None if kind == "teacher" else int(ou_key[-1])
        groups = select_provision_groups(
            kind=kind,
            zyklus=zyklus,
            groups_teacher=school.ad_groups_teacher,
            groups_student_zyklus1=school.ad_groups_student_zyklus1,
            groups_student_zyklus2=school.ad_groups_student_zyklus2,
            groups_student_zyklus3=school.ad_groups_student_zyklus3,
        )
        return ou, groups

    async def _template(self, template_id: int, school_id: int | None) -> GroupTemplate:
        """Die gewählte Zielgruppe, geprüft gegen den Ziel-Standort.

        Sie muss aktiv sein und an ``school_id`` angeboten werden — dort
        verknüpft oder global (ohne Standort-Bindung). Ohne Standort nur global.
        """
        repo = GroupTemplateRepository(self.session)
        tpl = await repo.get(template_id)
        if tpl is None or tpl.status != "active":
            raise UserAdminError("group_template_not_found")
        links = (await repo.school_ids_for([tpl.id])).get(tpl.id, [])
        if links and (school_id is None or school_id not in links):
            raise UserAdminError("group_template_not_for_school")
        return tpl

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
        school_id: int | None,
        group_template_id: int | None = None,
        ad_ou: str | None = None,
        display_name: str | None = None,
        force_change: bool | None = None,
        cannot_change_password: bool | None = None,
        password_never_expires: bool | None = None,
        jahrgangsstufe: int | None = None,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> CreatedUser:
        school = await self.session.get(School, school_id) if school_id is not None else None
        if school_id is not None and school is None:
            raise UserAdminError("school_not_found")
        # Die Zielgruppe bestimmt Kontoart (und damit die OU), Gruppen,
        # Passwortart und die Konto-Einstellungen. Ohne Zielgruppe gilt die
        # Kontoart aus ``ou_key`` mit den Gruppen des Standorts.
        tpl = (
            await self._template(group_template_id, school_id)
            if group_template_id is not None
            else None
        )
        if tpl is not None and tpl.kind in OU_CHOICES:
            ou_key = tpl.kind
        if ou_key not in OU_CHOICES:
            raise UserAdminError("invalid_ou_choice")
        # Eigene Ziel-OU: die bei der Anlage angegebene, sonst die der
        # Zielgruppe. Bei fester Kontoart legt der Standort die OU fest.
        # Bei fester Kontoart mit Standort legt der Standort die OU fest; ohne
        # Standort gilt die der Zielgruppe (oder die angegebene).
        fixed_with_school = tpl is not None and tpl.kind in FIXED_KINDS and school is not None
        if ad_ou and fixed_with_school:
            raise UserAdminError("ou_not_allowed_for_kind")
        own_ou = ad_ou or (tpl.ad_ou if tpl is not None and not fixed_with_school else None)
        if own_ou:
            # Die OU des Standorts braucht es dann nicht. Mit Standort muss sie
            # in ihm liegen, sonst verlöre der nächste Abgleich die Zuordnung.
            if school is not None and not ou_within_school(own_ou, school.scope_short):
                raise UserAdminError("ou_outside_school")
            ou_dn, group_dns = own_ou, []
        elif school is None:
            # Ohne Standort gibt es keine Standort-OU — nur eine eigene.
            raise UserAdminError("ou_required_without_school")
        else:
            ou_dn, group_dns = await self._provision_target(ou_key, school)
        if tpl is not None:
            group_dns = list(tpl.ad_groups or [])
        # Ein ausdrücklich gesetzter Wert gewinnt; sonst die Zielgruppe; sonst
        # die bisherige Vorgabe.
        if force_change is None:
            force_change = tpl.force_change if tpl is not None else True
        if cannot_change_password is None:
            cannot_change_password = tpl.cannot_change_password if tpl is not None else False
        if password_never_expires is None:
            password_never_expires = tpl.password_never_expires if tpl is not None else False
        profile = tpl.password_profile if tpl is not None else default_profile_for_kind(ou_key)
        kind = {"teacher": "teacher", "company": "company"}.get(ou_key, "student")
        display = (
            (display_name or "").strip() or f"{given_name} {surname}".strip() or sam_account_name
        )
        password = generate_for_profile(profile)

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
            # Mirror the groups we just assigned so the user shows them
            # immediately (a later AD sync reconciles to the real memberOf).
            groups=tuple(group_dns),
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
        stored = False
        if cache is not None:
            cache.cannot_change_password = cannot_change_password
            cache.group_template_id = tpl.id if tpl is not None else None
            # Tresor nur, wenn das Passwort so bleibt: ein änderbares oder
            # ablaufendes wäre in der Klassenliste bald falsch (wie beim Import).
            if (
                tpl is not None
                and tpl.store_password
                and password_stays(
                    force_change=force_change,
                    cannot_change_password=cannot_change_password,
                    password_never_expires=password_never_expires,
                )
            ):
                vault = PasswordVaultService(self.session, self.settings)
                if await vault.enabled():
                    cache.store_password = True
                    await self.session.flush()
                    await vault.store(guid, password)
                    stored = True
            # We know the target school explicitly — set it directly rather than
            # relying on the OU/scope_short resolver. Ohne Standort bleibt, was
            # der Resolver aus der OU liest — genau das tut auch der Abgleich.
            if school_id is not None:
                cache.school_id = school_id
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
            payload={
                "kind": kind,
                "upn": record.upn,
                "ou_key": ou_key,
                "group_template_id": group_template_id,
                "own_ou": bool(own_ou),
                "profile": profile,
                "vaulted": stored,
            },
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

        # Free any devices still assigned to this user — they return to the free
        # pool instead of staying stuck on a deleted objectGUID. The device's
        # open history period is closed (with the person snapshot preserved).
        await release_person_devices(
            self.session,
            self.settings,
            ad_object_guid,
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            ip=ip,
            request_id=request_id,
        )

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
