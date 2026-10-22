"""Wer darf die Konsole bedienen (ADR-0020 D4).

Drei Arten von Aufrufern, und nur eine ist eine Person:

| Art | Woran erkannt | Name im Protokoll |
|---|---|---|
| **Person** | Sitzungs-Cookie (Zertifikat + TOTP) | ihr UPN |
| **Dienst** | Service-Token | `service:<name>` |
| **Notzugang** | Bootstrap-Token | `bootstrap-token` |

`require_identity` lässt alle drei durch — für Flächen, die kein `actor`
brauchen (der Runner holt damit Update-Aufträge ab). `require_person` lässt
nur die erste und die dritte durch: was einen Namen in ein Kundenprotokoll
schreibt, soll nicht von einem Token im Container ausgehen.

Der Bootstrap-Token bleibt, weil er der einzige Weg in eine frisch ausgerollte
Konsole ist, in der noch kein Operator eingetragen ist. Er heisst im Protokoll
so, damit er auffällt.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import ServiceToken
from cockpit_api.services.console_auth import ConsoleAuthService, fingerprint_from_header

#: Name des Cookies mit der Sitzungs-Id.
SESSION_COOKIE = "cockpit_session"

#: Name des Bootstrap-Aufrufers im Protokoll. Kein UPN: es ist keine Person,
#: und es soll nicht aussehen wie eine.
BOOTSTRAP_ACTOR = "bootstrap-token"


class CallerKind(StrEnum):
    person = "person"
    service = "service"
    bootstrap = "bootstrap"


@dataclass(frozen=True)
class Caller:
    """Wer die Anfrage stellt."""

    kind: CallerKind
    #: Was in `actor` landet — der UPN einer Person, `service:<name>` oder
    #: `bootstrap-token`.
    actor: str
    #: Nur bei einer Person gesetzt.
    operator_id: int | None = None

    @property
    def is_person(self) -> bool:
        return self.kind is CallerKind.person


def _extract_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _token_caller(token: str, session: AsyncSession) -> Caller | None:
    if settings.bootstrap_token and secrets.compare_digest(token, settings.bootstrap_token):
        return Caller(kind=CallerKind.bootstrap, actor=BOOTSTRAP_ACTOR)
    digest = hash_token(token)
    stmt = select(ServiceToken).where(ServiceToken.token_hash == digest)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None or row.revoked or row.expires_at < datetime.now(UTC):
        return None
    row.last_used_at = datetime.now(UTC)
    # `description` und nicht `name`: die Spalte heisst so, und ein `row.name`
    # wäre erst beim ersten Dienst-Aufruf aufgefallen — mit einem
    # AttributeError statt einer Antwort.
    return Caller(kind=CallerKind.service, actor=f"service:{row.description}")


async def require_identity(
    request: Request,
    authorization: str | None = Header(default=None),
    x_console_client_cert: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Caller:
    """Irgendein zulässiger Aufrufer — Person, Dienst oder Notzugang.

    Reihenfolge: erst der Cookie, dann ein Token. Wer angemeldet ist, soll
    nicht an einem alten Token hängen bleiben, den der Browser noch mitschickt.
    """
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        fingerprint = fingerprint_from_header(x_console_client_cert)
        resolved = await ConsoleAuthService(session).resolve_session(
            cookie, fingerprint=fingerprint
        )
        if resolved is not None:
            _row, operator = resolved
            return Caller(kind=CallerKind.person, actor=operator.upn, operator_id=operator.id)

    token = _extract_token(authorization)
    if token:
        caller = await _token_caller(token, session)
        if caller is not None:
            await session.commit()
            return caller

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")


async def require_person(caller: Caller = Depends(require_identity)) -> Caller:
    """Nur ein Mensch — eine Sitzung oder der Notzugang.

    Ein Dienst-Token kommt hier nicht durch. Was einen Namen in das Protokoll
    eines Kunden schreibt (Einstellungen, Rechte-Matrix, Operator-Zugriff),
    soll nicht von einem Token ausgehen, das in einem Container liegt und
    keinen Menschen kennt.
    """
    if caller.kind is CallerKind.service:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Diese Fläche verlangt eine angemeldete Person, kein Dienst-Token (ADR-0020 D4).",
        )
    return caller


async def require_bootstrap_token(caller: Caller = Depends(require_identity)) -> None:
    """Rückwärtskompatibler Name für „irgendein zulässiger Aufrufer".

    Bleibt, damit der Umbau nicht jede Zeile anfasst; neue Flächen nehmen
    `require_identity` oder `require_person`.
    """
    return None


__all__ = [
    "BOOTSTRAP_ACTOR",
    "SESSION_COOKIE",
    "Caller",
    "CallerKind",
    "hash_token",
    "require_bootstrap_token",
    "require_identity",
    "require_person",
]
