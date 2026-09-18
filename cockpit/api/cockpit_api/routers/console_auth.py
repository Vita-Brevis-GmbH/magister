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
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api import passwords
from cockpit_api.auth import SESSION_COOKIE, Caller, require_identity
from cockpit_api.db import get_session
from cockpit_api.models.operator import ConsoleOperator, ConsoleSession
from cockpit_api.schemas.console_auth import (
    ConsoleEnrolmentOut,
    ConsoleLoginRequest,
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

#: Gegen den rechnet die Anmeldung, wenn es den Benutzer nicht gibt. Ohne das
#: antwortet ein unbekannter Benutzer messbar schneller als ein bekannter —
#: und damit sagt die Antwortzeit, welche Konten existieren.
_LEER_HASH = passwords.hash_password("kein-konto")

router = APIRouter(prefix="/auth/console", tags=["console-auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _jetzt() -> datetime:
    """Die Uhr des Servers, wie sie in jede Antwort geht.

    Damit kann die Oberfläche vergleichen, statt dass jemand rät: geht eine
    der beiden Uhren mehr als einen Zeitschritt daneben, ist der zweite
    Faktor nicht benutzbar, und „Der Code stimmt nicht" ist die falsche
    Auskunft.
    """
    return datetime.now(UTC)


async def _operator_im_gang(
    request: Request,
    svc: ConsoleAuthService,
    fingerprint: str | None,
) -> tuple[ConsoleOperator | None, ConsoleSession | None]:
    """Wer gerade mitten in der Anmeldung steckt — und woran man ihn erkennt.

    Zwei Wege führen zum zweiten Schritt (ADR-0023): das Client-Zertifikat
    (ADR-0020 D1) oder der Zwischenstand aus der Passwort-Anmeldung. Beide
    enden hier, damit `enrol` und `totp` nur einen Ablauf haben.
    """
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        resolved = await svc.resolve_session(cookie, fingerprint=None, allow_pending=True)
        if resolved is not None and resolved[0].pending_totp:
            return resolved[1], resolved[0]
    if fingerprint:
        return await svc.operator_for(fingerprint), None
    return None, None


@router.post("/login", response_model=ConsoleWhoamiOut)
async def login(
    request: Request,
    response: Response,
    body: ConsoleLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> ConsoleWhoamiOut:
    """Erster Faktor (ADR-0023 D1). Danach folgt der Code, nicht die Konsole.

    Jede Ablehnung ist derselbe 401: unbekannter Benutzer, falsches Passwort
    und gesperrt sind für den Vorleger nicht zu unterscheiden. Der Grund steht
    im Log des Betreibers.
    """
    svc = ConsoleAuthService(session)
    operator = await svc.operator_for_upn(body.upn)
    if operator is None:
        # Trotzdem rechnen: sonst antwortet ein unbekannter Benutzer
        # messbar schneller als ein bekannter.
        passwords.verify_password(body.password, _LEER_HASH)
        logger.warning("Konsole: Anmeldung für unbekannten Benutzer versucht.")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid")
    if svc.is_locked(operator):
        logger.warning("Konsole: Anmeldung für gesperrten Operator %s.", operator.upn)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid")
    if not await svc.verify_password(operator, body.password):
        await session.commit()
        logger.warning("Konsole: falsches Passwort für %s.", operator.upn)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid")

    row = await svc.start_session(
        operator,
        fingerprint=None,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        pending=True,
    )
    await session.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=row.id,
        httponly=True,
        samesite="strict",
        secure=True,
        path="/",
    )
    # Der Name geht mit: wer das Passwort kennt, weiss ohnehin, wer er ist.
    stufe = svc.stage_for(operator)
    return ConsoleWhoamiOut(server_time=_jetzt(), stage=stufe, upn=operator.upn, name=operator.name)


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
        resolved = await svc.resolve_session(cookie, fingerprint=fingerprint, allow_pending=True)
        if resolved is not None:
            row, operator = resolved
            await session.commit()
            if row.pending_totp:
                # Passwort gezeigt, Code fehlt. Die Oberfläche soll das
                # Codefeld zeigen und nicht die Anmeldemaske von vorn.
                return ConsoleWhoamiOut(
                    server_time=_jetzt(),
                    stage=svc.stage_for(operator),
                    upn=operator.upn,
                    name=operator.name,
                )
            return ConsoleWhoamiOut(
                server_time=_jetzt(),
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
        return ConsoleWhoamiOut(server_time=_jetzt(), stage=AuthStage.UNKNOWN)

    operator = await svc.operator_for(fingerprint)
    stage = svc.stage_for(operator)
    if operator is None:
        logger.warning("Konsole: unbekanntes Client-Zertifikat %s…", fingerprint[:12])
        return ConsoleWhoamiOut(server_time=_jetzt(), stage=stage)
    return ConsoleWhoamiOut(server_time=_jetzt(), stage=stage, upn=operator.upn, name=operator.name)


@router.post("/enrol", response_model=ConsoleEnrolmentOut)
async def enrol(
    request: Request,
    x_console_client_cert: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ConsoleEnrolmentOut:
    """Zweiten Faktor einrichten. Geheimnis und Codes gibt es **einmal**."""
    svc = ConsoleAuthService(session)
    fingerprint = fingerprint_from_header(x_console_client_cert)
    operator, _ = await _operator_im_gang(request, svc, fingerprint)
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
    operator, zwischenstand = await _operator_im_gang(request, svc, fingerprint)
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
    if zwischenstand is not None:
        # Aus dem Zwischenstand der Passwort-Anmeldung wird die Sitzung —
        # dieselbe Zeile, derselbe Cookie (ADR-0023 D2).
        await svc.promote_session(zwischenstand, operator)
        row = zwischenstand
    else:
        row = await svc.start_session(
            operator,
            fingerprint=fingerprint,
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
        server_time=_jetzt(),
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
