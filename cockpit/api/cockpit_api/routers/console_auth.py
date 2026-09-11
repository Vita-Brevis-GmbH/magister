"""`/api/auth/console` — Anmeldung an der Konsole (ADR-0020).

Der Ablauf hat drei Schritte, und der erste passiert vor der Anwendung: Caddy
verlangt ein Client-Zertifikat und gibt es als DER-base64 weiter. Danach:

1. `GET /whoami` sagt, was zu tun ist — unbekanntes Zertifikat, Einrichten,
   Code, oder schon angemeldet.
2. `POST /enrol` richtet den zweiten Faktor ein und zeigt Geheimnis und
   Wiederherstellungscodes **einmal**.
3. `POST /totp` prüft den Code und stellt die Sitzung aus.

Warum `GET /whoami` und nicht ein Formular, das alles auf einmal macht: der
Browser schickt das Zertifikat bei jeder Anfrage mit, und die Anwendung kann
daraus ableiten, welcher Schritt fehlt. Ein Anmeldeformular, das zuerst nach
einem Benutzernamen fragt, wäre eine Eingabe für etwas, das schon feststeht.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import SESSION_COOKIE, Caller, require_identity
from cockpit_api.db import get_session
from cockpit_api.schemas.console_auth import (
    ConsoleEnrolmentOut,
    ConsoleTotpRequest,
    ConsoleWhoamiOut,
)
from cockpit_api.services.console_auth import (
    AuthStage,
    ConsoleAuthError,
    ConsoleAuthService,
    fingerprint_from_header,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/console", tags=["console-auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/whoami", response_model=ConsoleWhoamiOut)
async def whoami(
    request: Request,
    x_console_client_cert: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ConsoleWhoamiOut:
    """Welcher Schritt fehlt. Absichtlich ohne Anmeldung erreichbar."""
    svc = ConsoleAuthService(session)
    fingerprint = fingerprint_from_header(x_console_client_cert)

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        resolved = await svc.resolve_session(cookie, fingerprint=fingerprint)
        if resolved is not None:
            row, operator = resolved
            await session.commit()
            return ConsoleWhoamiOut(
                stage=AuthStage.AUTHENTICATED,
                upn=operator.upn,
                name=operator.name,
                expires_at=row.expires_at,
            )

    if fingerprint is None:
        # Kein Zertifikat: in der Entwicklung der Normalfall, im Betrieb ein
        # Fehler in der Verdrahtung. Dieselbe Antwort wie bei einem
        # unbekannten Zertifikat — die Antwort soll nicht verraten, ob ein
        # Zertifikat bekannt wäre.
        return ConsoleWhoamiOut(stage=AuthStage.UNKNOWN)

    operator = await svc.operator_for(fingerprint)
    stage = svc.stage_for(operator)
    if operator is None:
        logger.warning("Konsole: unbekanntes Client-Zertifikat %s…", fingerprint[:12])
        return ConsoleWhoamiOut(stage=stage)
    return ConsoleWhoamiOut(stage=stage, upn=operator.upn, name=operator.name)


@router.post("/enrol", response_model=ConsoleEnrolmentOut)
async def enrol(
    x_console_client_cert: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ConsoleEnrolmentOut:
    """Zweiten Faktor einrichten. Geheimnis und Codes gibt es **einmal**."""
    svc = ConsoleAuthService(session)
    fingerprint = fingerprint_from_header(x_console_client_cert)
    operator = await svc.operator_for(fingerprint) if fingerprint else None
    if operator is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown_certificate")
    try:
        enrolment = await svc.begin_enrolment(operator)
    except ConsoleAuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    return ConsoleEnrolmentOut(
        secret=enrolment.secret,
        provisioning_uri=enrolment.provisioning_uri,
        qr_data_uri=enrolment.qr_data_uri,
        recovery_codes=enrolment.recovery_codes,
    )


@router.post("/totp", response_model=ConsoleWhoamiOut)
async def submit_totp(
    request: Request,
    response: Response,
    body: ConsoleTotpRequest,
    x_console_client_cert: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ConsoleWhoamiOut:
    """Code prüfen und Sitzung ausstellen.

    Jede Ablehnung ist derselbe 401: falscher Code, gesperrt oder unbekanntes
    Zertifikat sind für den Vorleger dasselbe. Der Grund steht im Log.
    """
    svc = ConsoleAuthService(session)
    fingerprint = fingerprint_from_header(x_console_client_cert)
    operator = await svc.operator_for(fingerprint) if fingerprint else None
    if operator is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid")
    if svc.stage_for(operator) is AuthStage.LOCKED:
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid")

    enrolling = operator.totp_confirmed_at is None
    try:
        ok = await svc.verify_second_factor(operator, body.code)
    except ConsoleAuthError as exc:
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid") from exc
    if not ok:
        await session.commit()
        logger.warning("Konsole: falscher zweiter Faktor für %s.", operator.upn)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid")

    if enrolling:
        await svc.confirm_enrolment(operator)
    row = await svc.start_session(
        operator,
        fingerprint=fingerprint or "",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=row.id,
        httponly=True,
        samesite="strict",
        # Der Listener ist ausschliesslich HTTPS (ADR-0015 D1); `secure` ist
        # hier keine Einstellung, sondern eine Tatsache.
        secure=True,
        path="/",
    )
    return ConsoleWhoamiOut(
        stage=AuthStage.AUTHENTICATED,
        upn=operator.upn,
        name=operator.name,
        expires_at=row.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    caller: Caller = Depends(require_identity),
    session: AsyncSession = Depends(get_session),
) -> None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        await ConsoleAuthService(session).end_session(cookie)
        await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


__all__ = ["router"]
