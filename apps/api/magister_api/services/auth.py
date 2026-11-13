"""Auth service: OIDC callback → login account → bootstrap → session → audit (ADR-0025).

Caller (router) is responsible for setting cookies on the response. This
service mutates the DB and emits audit events; cookie semantics belong to HTTP.

Since ADR-0025 the sign-in no longer depends on the AD sync: every user of the
customer's Keycloak realm gets a login account on the first sign-in. Whether
the account may *see* anything is decided by role assignments only — an
account without any lands on a page that says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.bootstrap import maybe_bootstrap_admin
from magister_api.auth.oidc import OidcUserInfo
from magister_api.auth.sessions import new_session_id
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, Session
from magister_api.repositories.auth import SessionRepository
from magister_api.services.login_accounts import LoginAccountService, LoginRefusedError


@dataclass(frozen=True)
class LoginResult:
    session: Session
    bootstrap_granted: bool
    account_created: bool


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
        """Resolve the login account → bootstrap-if-listed → create session → audit."""
        audit = AuditService(self.session, self.settings)
        accounts = LoginAccountService(self.session, self.settings)

        try:
            resolution = await accounts.resolve_for_login(userinfo)
            account = resolution.account
            if not account.enabled:
                raise LoginRefusedError("account_disabled")
            # Ist das Konto einer AD-Person zugeordnet und die im AD
            # deaktiviert (Austritt), gibt es keine Sitzung — auch wenn der
            # Benutzer in Keycloak noch steht.
            # scope-bypass: the signing-in user's own AD row, by primary key.
            ad_row = await self.session.get(AdUserCache, account.principal_guid)
            if ad_row is not None and not ad_row.enabled:
                raise LoginRefusedError("user_disabled")
        except LoginRefusedError as exc:
            # Eine abgewiesene Anmeldung gehört ins Protokoll des Kunden: wer
            # unter einem vergebenen Namen hinein wollte, soll dort stehen.
            await audit.emit(
                action="login_refused",
                target_kind="login_account",
                target_id=userinfo.username[:64],
                actor_upn=userinfo.username,
                actor_object_guid=None,
                school_id=None,
                ip=ip,
                request_id=request_id,
                payload={
                    "reason": exc.code,
                    "oidc_subject": userinfo.subject,
                    "user_agent": user_agent,
                },
            )
            raise

        if resolution.created or resolution.bound:
            await audit.emit(
                action="login_account_created" if resolution.created else "login_account_bound",
                target_kind="login_account",
                target_id=str(account.id),
                actor_upn=account.username,
                actor_object_guid=account.principal_guid,
                school_id=None,
                ip=ip,
                request_id=request_id,
                payload={
                    "username": account.username,
                    "oidc_subject": userinfo.subject,
                    "principal_guid": account.principal_guid,
                    "ad_linked": ad_row is not None,
                    "via": "login",
                },
            )

        LoginAccountService.note_login(account, userinfo)

        bootstrap = await maybe_bootstrap_admin(
            session=self.session,
            settings=self.settings,
            username=account.username,
            principal_guid=account.principal_guid,
        )

        sessions_repo = SessionRepository(self.session)
        sid = new_session_id()
        sess = await sessions_repo.create(
            session_id=sid,
            ad_object_guid=account.principal_guid,
            oidc_subject=userinfo.subject,
            lifetime=timedelta(minutes=self.settings.session_lifetime_minutes),
            ip=ip,
            user_agent=user_agent,
        )

        await audit.emit(
            action="login",
            target_kind="session",
            target_id=sess.id[:12],  # short prefix only; full id is the cookie value
            actor_upn=account.username,
            actor_object_guid=account.principal_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={
                "oidc_subject": userinfo.subject,
                "bootstrap_granted": bootstrap.granted,
                "account_created": resolution.created,
                "user_agent": user_agent,
            },
        )
        if bootstrap.granted:
            await audit.emit(
                action="role_granted",
                target_kind="role_assignment",
                target_id=account.principal_guid,
                actor_upn="bootstrap",
                actor_object_guid=None,
                school_id=None,
                ip=ip,
                request_id=request_id,
                payload={"role": "admin", "school_id": None, "via": "bootstrap_env"},
            )

        return LoginResult(
            session=sess,
            bootstrap_granted=bootstrap.granted,
            account_created=resolution.created,
        )

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


__all__ = ["AuthService", "LoginRefusedError", "LoginResult"]
