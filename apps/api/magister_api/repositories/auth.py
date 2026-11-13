"""Repositories for sessions, role assignments, login accounts, AD-user-cache lookups."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import Exists

from magister_api.models.auth import AdUserCache, LoginAccount, RoleAssignment, Session
from magister_api.models.base import utcnow
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.manager_role import ManagerRole
from magister_api.models.subject_teacher_role import SubjectTeacherRole

#: Tabellen mit abgeleiteten Zuordnungen und Gültigkeitsfenster.
_Assignment = type[ClassTeacherRole] | type[SubjectTeacherRole] | type[ManagerRole]


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
        operator_upn: str | None = None,
        operator_jti: uuid.UUID | None = None,
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
            # Nur bei auth_kind="operator" gesetzt (ADR-0019 D5).
            operator_upn=operator_upn,
            operator_jti=operator_jti,
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

    async def delete_oidc_for(self, ad_object_guid: str) -> int:
        """End every OIDC session of one principal (account locked or unbound)."""
        stmt = (
            delete(Session)
            .where(Session.ad_object_guid == ad_object_guid, Session.auth_kind == "oidc")
            .returning(Session.id)
        )
        ended = (await self.session.execute(stmt)).scalars().all()
        await self.session.flush()
        return len(ended)


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

    async def list_all_active(self) -> list[RoleAssignment]:
        """Every active admin/schulleitung/smi grant across all users.

        # scope-bypass: the roles overview is admin-only (require_admin) and is
        # deliberately cross-school — it exists to show who holds which role.
        """
        stmt = select(RoleAssignment).where(RoleAssignment.revoked_at.is_(None))
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
        revoked = await self._find_revoked(ad_object_guid, role, school_id)
        if revoked is not None:
            # Die Eindeutigkeit (Person, Rolle, Einheit) gilt auch für
            # zurückgenommene Zeilen (uq_role_assignments_user_role_school).
            # Neu vergeben heisst deshalb: die zurückgenommene Zeile lebt mit
            # neuer Herkunft wieder auf — ein zweites INSERT scheiterte. Den
            # Verlauf (wer wann vergab und entzog) hält das Audit.
            revoked.revoked_at = None
            revoked.granted_by = granted_by
            revoked.granted_at = utcnow()
            await self.session.flush()
            return revoked
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

    async def delete_for_school(self, school_id: int, *, granted_by: str) -> list[RoleAssignment]:
        """Alle Zeilen einer Herkunft an einer Einheit löschen, aktive und zurückgenommene.

        Nur für das Löschen der Einheit (Fremdschlüssel RESTRICT). Gibt die
        gelöschten Zeilen zurück, damit die aktiven auditiert werden können.

        # scope-bypass: admin-only delete path of the school itself.
        """
        stmt = (
            delete(RoleAssignment)
            .where(RoleAssignment.school_id == school_id, RoleAssignment.granted_by == granted_by)
            .returning(RoleAssignment)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        await self.session.flush()
        return rows

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

    async def _find_revoked(
        self, ad_object_guid: str, role: str, school_id: int | None
    ) -> RoleAssignment | None:
        """Die zuletzt zurückgenommene Zeile dieses Tripels, falls es eine gibt."""
        cond = and_(
            RoleAssignment.ad_object_guid == ad_object_guid,
            RoleAssignment.role == role,
            RoleAssignment.revoked_at.is_not(None),
            RoleAssignment.school_id.is_(None)
            if school_id is None
            else RoleAssignment.school_id == school_id,
        )
        stmt = (
            select(RoleAssignment)
            .where(cond)
            .order_by(RoleAssignment.revoked_at.desc(), RoleAssignment.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class AdUserCacheRepository:
    """Read-mostly repository — population is owned by the AD sync (issue #3)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_upn(self, upn: str) -> AdUserCache | None:
        """The AD user whose UPN equals ``upn`` (case-insensitive).

        # scope-bypass: used only at sign-in to map a Keycloak user name onto
        # the AD object of the same person (ADR-0025); the caller learns the
        # GUID of exactly that one row and never lists anything.
        """
        stmt = select(AdUserCache).where(func.lower(AdUserCache.upn) == upn.strip().lower())
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


class LoginAccountRepository:
    """Anmeldekonten aus dem Keycloak-Realm (ADR-0025).

    # scope-bypass: Anmeldekonten tragen keinen Standort. Sie sind die
    # Identität für die Anmeldung, nicht Personendaten einer Schule; gelesen
    # werden sie bei der Anmeldung (das eigene Konto) und in der
    # Admin-Oberfläche (require_admin, standortübergreifend wie die Rollen).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, account_id: int) -> LoginAccount | None:
        return await self.session.get(LoginAccount, account_id)

    async def get_by_subject(self, *, issuer: str, subject: str) -> LoginAccount | None:
        stmt = select(LoginAccount).where(
            LoginAccount.issuer == issuer, LoginAccount.subject == subject
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_username(self, username: str) -> LoginAccount | None:
        stmt = select(LoginAccount).where(LoginAccount.username == username.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_principal(self, principal_guid: str) -> LoginAccount | None:
        stmt = select(LoginAccount).where(LoginAccount.principal_guid == principal_guid)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_principals(self, guids: list[str]) -> list[LoginAccount]:
        if not guids:
            return []
        stmt = select(LoginAccount).where(LoginAccount.principal_guid.in_(guids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def search(self, *, search: str | None, limit: int) -> list[LoginAccount]:
        stmt = select(LoginAccount)
        if search:
            needle = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    LoginAccount.username.like(needle),
                    func.lower(LoginAccount.display_name).like(needle),
                    func.lower(LoginAccount.email).like(needle),
                )
            )
        stmt = stmt.order_by(LoginAccount.username).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, row: LoginAccount) -> LoginAccount:
        self.session.add(row)
        await self.session.flush()
        return row

    async def has_assignments(self, principal_guid: str) -> bool:
        """Does anything grant this principal access — role, class, subject, unit?

        Rollen aus ``role_assignments`` stehen schon im Benutzer; hier zählen
        die abgeleiteten Zuordnungen (Klassen- und Fachlehrer, Leitung einer
        Abteilung), die nur in ihren eigenen Tabellen stehen.
        """
        now = utcnow()

        def _active(model: _Assignment) -> Exists:
            return exists().where(
                model.ad_object_guid == principal_guid,
                model.valid_from <= now,
                or_(model.valid_to.is_(None), model.valid_to >= now),
            )

        stmt = select(
            or_(
                _active(ClassTeacherRole),
                _active(SubjectTeacherRole),
                _active(ManagerRole),
            )
        )
        return bool((await self.session.execute(stmt)).scalar())
