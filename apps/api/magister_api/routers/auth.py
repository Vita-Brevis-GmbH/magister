"""Auth router: OIDC login/callback/logout + ``/auth/me``.

The OIDC client is injected via a FastAPI dependency so tests can swap in a
mock. The router shape is intentionally small — anything beyond cookie wiring
lives in :mod:`magister_api.services.auth`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.csrf import issue_csrf_token
from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.auth.effective_settings import get_effective_settings
from magister_api.auth.oidc import EntraOidcClient, OidcClient
from magister_api.auth.sessions import new_session_id
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.auth import SessionRepository
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.schemas.auth import CurrentUserOut
from magister_api.schemas.local_admin import LocalLoginRequest
from magister_api.services.auth import AuthService, LoginRefusedError
from magister_api.services.local_admin import (
    LOCAL_ADMIN_GUID,
    LocalAdminService,
    LoginFailed,
    LoginRefusal,
)

OIDC_FLOW_COOKIE = "magister_oidc_flow"

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])


def get_oidc_client(
    request: Request,
    eff: Settings = Depends(get_effective_settings),
) -> OidcClient:
    """OIDC client built from the effective (DB-overlaid) settings.

    Cached on ``app.state`` keyed by ``effective_settings`` identity so we
    don't construct a new ``EntraOidcClient`` per request — the dep above
    already returns the same Settings instance until the version bumps.
    """
    cached: tuple[int, OidcClient] | None = getattr(request.app.state, "_oidc_client_cache", None)
    if cached is not None and cached[0] == id(eff):
        return cached[1]
    client = EntraOidcClient(eff)
    request.app.state._oidc_client_cache = (id(eff), client)
    return client


def _flow_serializer(settings: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(
        settings.session_secret.get_secret_value() or "dev-only-not-for-prod",
        salt="magister.oidc.flow",
    )


def _set_session_cookie(response: Response, value: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=value,
        max_age=settings.session_lifetime_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def _set_csrf_cookie(response: Response, value: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=value,
        max_age=settings.session_lifetime_minutes * 60,
        httponly=False,  # readable by JS so it can be put in the X-CSRF-Token header
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


@router.get("/login")
async def login(
    request: Request,
    settings: Settings = Depends(get_effective_settings),
    oidc: OidcClient = Depends(get_oidc_client),
) -> RedirectResponse:
    if not settings.oidc_issuer or not settings.oidc_client_id:
        raise HTTPException(status_code=503, detail="oidc_not_configured")
    auth_req = oidc.build_authorize_request()
    flow_state = _flow_serializer(settings).dumps(
        {
            "state": auth_req.state,
            "nonce": auth_req.nonce,
            "code_verifier": auth_req.code_verifier,
        }
    )
    response = RedirectResponse(url=auth_req.url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=OIDC_FLOW_COOKIE,
        value=flow_state,
        max_age=600,  # 10 min for the round-trip
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",  # OIDC redirect is cross-site
        # Path "/" instead of "/auth" so the cookie survives a reverse-proxy
        # like Caddy that mounts the API under a sub-prefix (e.g. /api/auth/*).
        # Still HttpOnly + 10-min TTL.
        path="/",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    flow_cookie: str | None = Cookie(default=None, alias=OIDC_FLOW_COOKIE),
    settings: Settings = Depends(get_effective_settings),
    oidc: OidcClient = Depends(get_oidc_client),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if error:
        raise HTTPException(status_code=400, detail=f"oidc_error:{error}")
    if not code or not state or not flow_cookie:
        raise HTTPException(status_code=400, detail="oidc_callback_invalid")
    try:
        flow = _flow_serializer(settings).loads(flow_cookie)
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="oidc_flow_tampered") from exc
    try:
        userinfo = await oidc.exchange_code(
            code=code,
            state=state,
            expected_state=flow["state"],
            code_verifier=flow["code_verifier"],
            nonce=flow["nonce"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    auth_service = AuthService(session, settings)
    request_id = getattr(request.state, "request_id", "")
    client_ip = getattr(request.state, "client_ip", None)
    user_agent = request.headers.get("user-agent")
    try:
        result = await auth_service.complete_oidc_login(
            userinfo=userinfo,
            ip=client_ip,
            user_agent=user_agent,
            request_id=request_id,
        )
    except LoginRefusedError as exc:
        raise HTTPException(status_code=403, detail=exc.code) from exc

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OIDC_FLOW_COOKIE, path="/")
    _set_session_cookie(response, result.session.id, settings)
    _set_csrf_cookie(response, issue_csrf_token(result.session.id, settings), settings)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=400, detail="no_session_cookie")
    auth_service = AuthService(session, settings)
    request_id = getattr(request.state, "request_id", "")
    client_ip = getattr(request.state, "client_ip", None)
    await auth_service.logout(
        session_id=cookie,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=client_ip,
        request_id=request_id,
    )
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=CurrentUserOut)
async def me(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CurrentUserOut:
    # Enrich with the cached name fields so the UI can greet by display name
    # (or full name) instead of the raw UPN. scope-bypass: this is the
    # authenticated user looking up their own row.
    from magister_api.models.auth import AdUserCache

    cache = await session.get(AdUserCache, user.ad_object_guid)
    return CurrentUserOut(
        ad_object_guid=user.ad_object_guid,
        upn=user.upn,
        given_name=cache.given_name if cache else None,
        surname=cache.surname if cache else None,
        display_name=cache.display_name if cache else None,
        is_admin=user.is_admin,
        school_scope=list(user.school_scope),
        roles=list(user.roles),
        expires_at=user.expires_at,  # type: ignore[arg-type]
    )


@router.get("/capabilities")
async def capabilities(
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Tell the SPA which login paths to render.

    Public + unauthenticated by design — the page that calls this is the
    pre-login screen. Returns booleans only (no secrets). OIDC reads from
    the DB-overlaid effective settings, so toggling OIDC config in the GUI
    immediately reflects without a process restart.
    """
    oidc_enabled = bool(settings.oidc_issuer and settings.oidc_client_id)
    local_row = await LocalAdminRepository(session).get()
    local_login_enabled = local_row is not None and local_row.enabled
    return {"oidc_enabled": oidc_enabled, "local_login_enabled": local_login_enabled}


_REFUSAL_TO_STATUS: dict[LoginRefusal, int] = {
    LoginRefusal.UNKNOWN_USER: status.HTTP_401_UNAUTHORIZED,
    LoginRefusal.WRONG_PASSWORD: status.HTTP_401_UNAUTHORIZED,
    LoginRefusal.DISABLED: status.HTTP_403_FORBIDDEN,
    LoginRefusal.LOCKED: status.HTTP_423_LOCKED,
}


@router.post("/login/local")
# 20/min keeps the IP-level brute-force ceiling generous enough that the
# per-account lockout (5 consecutive failures, see LocalAdminService) is the
# binding constraint for an interactive operator typo, while still cutting
# off automated attackers fast.
@limiter.limit("20/minute")  # pyright: ignore[reportUntypedFunctionDecorator]
async def login_local(
    request: Request,
    payload: LocalLoginRequest,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Username + password login for the break-glass local admin.

    CSRF-exempt (predates the session) via the existing `/auth/login` prefix
    in :class:`CsrfMiddleware.EXEMPT_PATH_PREFIXES`. Rate-limited per IP.
    """
    svc = LocalAdminService(session)
    result = await svc.authenticate(payload.username, payload.password)
    request_id = getattr(request.state, "request_id", "")
    client_ip = getattr(request.state, "client_ip", None)
    user_agent = request.headers.get("user-agent")

    if isinstance(result, LoginFailed):
        # Audit the failure (no payload secrets — allowlist enforces).
        audit = AuditService(session, settings)
        await audit.emit(
            action="local_login_failed",
            target_kind="local_admin",
            target_id=payload.username[:64],
            actor_upn=f"{payload.username}@magister.local",
            actor_object_guid=None,
            school_id=None,
            ip=client_ip,
            request_id=request_id,
            payload={"reason": result.reason.value},
        )
        # Return a JSONResponse rather than raising HTTPException: the
        # session-per-request wrapper rolls back on raised exceptions,
        # which would undo the failed_login_count increment that drives
        # the per-account lockout.
        return JSONResponse(
            status_code=_REFUSAL_TO_STATUS[result.reason],
            content={"detail": result.reason.value},
        )

    # result is narrowed to LoginOk here: the LoginFailed branch above returns.
    sid = new_session_id()
    sessions_repo = SessionRepository(session)
    await sessions_repo.create(
        session_id=sid,
        ad_object_guid=LOCAL_ADMIN_GUID,
        oidc_subject="",  # not an OIDC session
        lifetime=timedelta(minutes=settings.session_lifetime_minutes),
        ip=client_ip,
        user_agent=user_agent,
        auth_kind="local",
    )
    audit = AuditService(session, settings)
    await audit.emit(
        action="local_login",
        target_kind="session",
        target_id=sid[:12],
        actor_upn=f"{result.admin.username}@magister.local",
        actor_object_guid=LOCAL_ADMIN_GUID,
        school_id=None,
        ip=client_ip,
        request_id=request_id,
        payload={"user_agent": user_agent},
    )

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_session_cookie(response, sid, settings)
    _set_csrf_cookie(response, issue_csrf_token(sid, settings), settings)
    return response


__all__ = ["router", "limiter", "get_oidc_client"]
