"""Auth router: OIDC login/callback/logout + ``/auth/me``.

The OIDC client is injected via a FastAPI dependency so tests can swap in a
mock. The router shape is intentionally small — anything beyond cookie wiring
lives in :mod:`magister_api.services.auth`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.csrf import issue_csrf_token
from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.auth.oidc import EntraOidcClient, OidcClient
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.schemas.auth import CurrentUserOut
from magister_api.services.auth import AuthService, LoginRefusedError

OIDC_FLOW_COOKIE = "magister_oidc_flow"

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])


def get_oidc_client(settings: Settings = Depends(get_settings)) -> OidcClient:
    return EntraOidcClient(settings)


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
    settings: Settings = Depends(get_settings),
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
        path="/auth",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    flow_cookie: str | None = Cookie(default=None, alias=OIDC_FLOW_COOKIE),
    settings: Settings = Depends(get_settings),
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
    response.delete_cookie(OIDC_FLOW_COOKIE, path="/auth")
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
async def me(user: AuthenticatedUser = Depends(get_current_user)) -> CurrentUserOut:
    return CurrentUserOut(
        ad_object_guid=user.ad_object_guid,
        upn=user.upn,
        is_admin=user.is_admin,
        school_scope=list(user.school_scope),
        roles=list(user.roles),
        expires_at=user.expires_at,  # type: ignore[arg-type]
    )


__all__ = ["router", "limiter", "get_oidc_client"]
