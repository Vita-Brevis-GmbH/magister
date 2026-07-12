"""Auth service: orchestrates OIDC callback → session creation + bootstrap + audit.

Caller (router) is responsible for setting cookies on the response. This
service mutates the DB and emits audit events; cookie semantics belong to HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.audit.service import AuditService
from magister_api.auth.bootstrap import maybe_bootstrap_admin
from magister_api.auth.oidc import OidcUserInfo
from magister_api.auth.sessions import new_session_id
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, Session
from magister_api.models.school import School
from magister_api.repositories.ad_users import AdUserCacheSyncRepository
from magister_api.repositories.auth import (
    AdUserCacheRepository,
    SessionRepository,
)


class LoginRefusedError(Exception):
    """Raised when a successful OIDC handshake should not yield a session.

    Examples: user has no AD-cache entry yet (no sync ran) and is not a bootstrap
    admin. The caller maps this to a 403 with an actionable message.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LoginResult:
    session: Session
    bootstrap_granted: bool


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def complete_oidc_login(
        self,
        *,
        userinfo: OidcUserInfo,
        ip: str | None,
        user_agent: str | None,
        request_id: str,
    ) -> LoginResult:
        """Match OIDC user → bootstrap-if-applicable → create session → audit."""
        cache_repo = AdUserCacheRepository(self.session)

        # Try to match an existing cache row first (oid then UPN).
        cache_row = await cache_repo.find_by_oidc_subject(oid=userinfo.oid, upn=userinfo.upn)

        bootstrap_granted = False
        if cache_row is None:
            # No prior sync. Bootstrap path is the only way to login at this point.
            ad_object_guid = userinfo.oid or ""
            if not ad_object_guid:
                raise LoginRefusedError("oidc_no_oid_for_bootstrap")
            bootstrap_result = await maybe_bootstrap_admin(
                session=self.session,
                settings=self.settings,
                upn=userinfo.upn,
                ad_object_guid=ad_object_guid,
                oidc_oid=userinfo.oid,
            )
            if not bootstrap_result.granted and not bootstrap_result.already_admin:
                raise LoginRefusedError("user_not_synced")
            bootstrap_granted = bootstrap_result.granted
            cache_row = await cache_repo.find_by_oidc_subject(oid=userinfo.oid, upn=userinfo.upn)
            if cache_row is None:
                raise LoginRefusedError("user_not_synced")
        else:
            # Re-run bootstrap to allow operator-driven re-grants.
            bootstrap_result = await maybe_bootstrap_admin(
                session=self.session,
                settings=self.settings,
                upn=userinfo.upn,
                ad_object_guid=cache_row.ad_object_guid,
                oidc_oid=userinfo.oid,
            )
            bootstrap_granted = bootstrap_result.granted

        if not cache_row.enabled:
            raise LoginRefusedError("user_disabled")

        sessions_repo = SessionRepository(self.session)
        sid = new_session_id()
        sess = await sessions_repo.create(
            session_id=sid,
            ad_object_guid=cache_row.ad_object_guid,
            oidc_subject=userinfo.subject,
            lifetime=timedelta(minutes=self.settings.session_lifetime_minutes),
            ip=ip,
            user_agent=user_agent,
        )

        audit = AuditService(self.session, self.settings)
        await audit.emit(
            action="login",
            target_kind="session",
            target_id=sess.id[:12],  # short prefix only; full id is the cookie value
            actor_upn=userinfo.upn,
            actor_object_guid=cache_row.ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={
                "oidc_subject": userinfo.subject,
                "bootstrap_granted": bootstrap_granted,
                "user_agent": user_agent,
            },
        )
        if bootstrap_granted:
            await audit.emit(
                action="role_granted",
                target_kind="role_assignment",
                target_id=cache_row.ad_object_guid,
                actor_upn="bootstrap",
                actor_object_guid=None,
                school_id=None,
                ip=ip,
                request_id=request_id,
                payload={"role": "admin", "school_id": None, "via": "bootstrap_env"},
            )

        return LoginResult(session=sess, bootstrap_granted=bootstrap_granted)

    async def complete_ad_login(
        self,
        *,
        ad: AdClient,
        login: str,
        password: str,
        ip: str | None,
        user_agent: str | None,
        request_id: str,
    ) -> LoginResult:
        """Authenticate against AD (LDAPS bind + login-group), then create a session.

        Raises :class:`LoginRefusedError` on any auth/authorization failure
        (``ad_login_disabled`` / ``ad_login_failed`` / ``user_disabled``). The
        password never leaves this call and is never logged.
        """
        if not self.settings.ad_login_enabled:
            raise LoginRefusedError("ad_login_disabled")

        record = await ad.authenticate(login=login, password=password)
        if record is None:
            raise LoginRefusedError("ad_login_failed")

        # Upsert the authenticated user into ad_user_cache so a session (and the
        # later role lookups) have a row to hang off — mirrors the sync writer,
        # including school resolution by OU.
        resolver = await self._school_resolver()
        await AdUserCacheSyncRepository(self.session).upsert_from_ad(
            [record], school_id_resolver=resolver
        )
        cache_row = await self.session.get(AdUserCache, record.ad_object_guid)
        if cache_row is None or not cache_row.enabled:
            raise LoginRefusedError("user_disabled")

        sessions_repo = SessionRepository(self.session)
        sid = new_session_id()
        sess = await sessions_repo.create(
            session_id=sid,
            ad_object_guid=record.ad_object_guid,
            oidc_subject="",  # not an OIDC session
            lifetime=timedelta(minutes=self.settings.session_lifetime_minutes),
            ip=ip,
            user_agent=user_agent,
            auth_kind="ad",
        )
        audit = AuditService(self.session, self.settings)
        await audit.emit(
            action="ad_login",
            target_kind="session",
            target_id=sess.id[:12],
            actor_upn=record.upn,
            actor_object_guid=record.ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"user_agent": user_agent},
        )
        return LoginResult(session=sess, bootstrap_granted=False)

    async def _school_resolver(self):
        """Return ``record -> school_id | None`` driven by the OU→scope_short match.

        Mirrors :class:`magister_api.services.ad_sync.AdSyncService` so a login
        upsert lands the user in the same school the periodic sync would.
        """
        # scope-bypass: login upsert runs as the auth service, not a scoped user.
        schools = list((await self.session.execute(select(School))).scalars().all())

        def _resolve(record: AdUserRecord) -> int | None:
            for s in schools:
                if record.matches_school_via_ou(s.scope_short):
                    return s.id
            return None

        return _resolve

    async def logout(
        self,
        *,
        session_id: str,
        actor_upn: str,
        actor_object_guid: str,
        ip: str | None,
        request_id: str,
    ) -> None:
        sessions_repo = SessionRepository(self.session)
        await sessions_repo.delete(session_id)
        audit = AuditService(self.session, self.settings)
        await audit.emit(
            action="logout",
            target_kind="session",
            target_id=session_id[:12],
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={},
        )
