"""Wer bedient die Konsole (ADR-0020).

Zwei Schritte, und beide sind nötig:

1. **Das Client-Zertifikat** sagt, welches Gerät anklopft. Caddy hat es gegen
   die Plattform-CA geprüft; hier wird aus dem öffentlichen Schlüssel ein
   Fingerprint gebildet und damit die Operator-Zeile gesucht (D1).
2. **Der TOTP-Code** sagt, dass die Person dabei ist. Erst danach entsteht
   eine Sitzung (D2).

Die Mechanik des zweiten Faktors ist die von ADR-0015 D2 — Geheimnis
verschlüsselt, letzter Schritt gespeichert, zehn Wiederherstellungscodes,
Sperre nach fünf Fehlversuchen. Bewusst dieselbe, nicht eine neue.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api import totp
from cockpit_api.config import settings
from cockpit_api.models.operator import ConsoleOperator, ConsoleSession
from cockpit_api.services.connector_ca import spki_fingerprint_from_der_base64

logger = logging.getLogger(__name__)

#: Was die Authenticator-App neben dem Code anzeigt.
TOTP_ISSUER = "Magister Konsole"

#: Fehlversuche am zweiten Faktor, dann Sperre. Dieselben Werte wie beim
#: lokalen Notkonto der Datenebene.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

_hasher = PasswordHasher()


class ConsoleAuthError(RuntimeError):
    """Anmeldung nicht möglich. Der Grund steht im Log, nicht in der Antwort."""


class AuthStage(StrEnum):
    """Was als Nächstes zu tun ist."""

    #: Kein oder ein unbekanntes Zertifikat. Kein Hinweis darauf, welches von
    #: beidem — das wäre eine Auskunft darüber, welche Zertifikate es gibt.
    UNKNOWN = "unknown_certificate"
    #: Zertifikat bekannt, zweiter Faktor noch nicht eingerichtet.
    ENROL = "enrolment_required"
    #: Zertifikat bekannt, Code fehlt.
    TOTP = "totp_required"
    #: Sitzung steht.
    AUTHENTICATED = "authenticated"
    #: Zu viele Fehlversuche.
    LOCKED = "locked"


@dataclass(frozen=True)
class Enrolment:
    """Was genau **einmal** zu sehen ist."""

    secret: str
    provisioning_uri: str
    qr_data_uri: str
    recovery_codes: list[str]


def fingerprint_from_header(value: str | None) -> str | None:
    """Fingerprint aus dem Zertifikats-Header, oder `None`.

    `None` heisst „kein Zertifikat" und ist kein Fehler: bei einer
    Installation ohne Client-Prüfung (Entwicklung) gibt es den Header nicht,
    und dann greift der Notzugang über den Bootstrap-Token.
    """
    if not value or not value.strip():
        return None
    try:
        return spki_fingerprint_from_der_base64(value)
    except Exception as exc:
        # Ein unlesbares Zertifikat ist kein Absturz. Caddy hat eines geprüft;
        # kommt hier etwas anderes an, ist die Verdrahtung falsch, und das
        # gehört in den Log des Betreibers.
        logger.warning("Client-Zertifikat im Header ist nicht lesbar: %s", exc)
        return None


class ConsoleAuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _key(self) -> str:
        if not settings.secret_key:
            raise ConsoleAuthError(
                "COCKPIT_SECRET_KEY ist nicht gesetzt. Ohne ihn kann der zweite "
                "Faktor nicht geprüft werden (ADR-0020 D2)."
            )
        return settings.secret_key

    async def operator_for(self, fingerprint: str) -> ConsoleOperator | None:
        stmt = select(ConsoleOperator).where(
            ConsoleOperator.spki_fingerprint == fingerprint,
            ConsoleOperator.enabled.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def stage_for(self, operator: ConsoleOperator | None) -> AuthStage:
        if operator is None:
            return AuthStage.UNKNOWN
        if operator.locked_until is not None and operator.locked_until > datetime.now(UTC):
            return AuthStage.LOCKED
        if operator.totp_confirmed_at is None:
            return AuthStage.ENROL
        return AuthStage.TOTP

    async def begin_enrolment(self, operator: ConsoleOperator) -> Enrolment:
        """Ein neues Geheimnis und zehn Codes — einmal sichtbar.

        Auch bei einem bereits **begonnenen**, aber nicht bestätigten
        Enrolment: wer die Seite geschlossen hat, soll neu anfangen können. Ein
        bestätigtes Enrolment wird dagegen nicht überschrieben — sonst könnte
        ein gestohlenes Zertifikat allein den zweiten Faktor austauschen.
        """
        if operator.totp_confirmed_at is not None:
            raise ConsoleAuthError("Der zweite Faktor ist schon eingerichtet.")
        secret = totp.new_secret()
        codes = totp.new_recovery_codes()
        uri = totp.provisioning_uri(secret, account=operator.upn, issuer=TOTP_ISSUER)
        await self.session.execute(
            ConsoleOperator.__table__.update()
            .where(ConsoleOperator.id == operator.id)
            .values(
                totp_secret_enc=func.pgp_sym_encrypt(secret, self._key()),
                totp_confirmed_at=None,
                totp_last_step=None,
                recovery_codes=[_hasher.hash(code) for code in codes],
            )
        )
        await self.session.flush()
        logger.info("Zweiter Faktor für %s eingerichtet (unbestätigt).", operator.upn)
        return Enrolment(
            secret=secret,
            provisioning_uri=uri,
            qr_data_uri=totp.qr_data_uri(uri),
            recovery_codes=codes,
        )

    async def _secret_of(self, operator_id: int) -> str | None:
        stmt = select(
            func.pgp_sym_decrypt(ConsoleOperator.totp_secret_enc, self._key()).label("secret")
        ).where(ConsoleOperator.id == operator_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def verify_second_factor(self, operator: ConsoleOperator, code: str) -> bool:
        """Code oder Wiederherstellungscode prüfen und die Zeile nachführen.

        Ein TOTP-Code gilt **einmal**: der akzeptierte Zeitschritt wird
        gespeichert, und ein Code aus demselben oder einem älteren Schritt
        wird abgewiesen. Ohne das wäre ein abgelesener Code eine halbe Minute
        lang brauchbar.
        """
        secret = await self._secret_of(operator.id)
        if not secret:
            raise ConsoleAuthError("Kein zweiter Faktor eingerichtet.")

        step = totp.verify_code(secret, code, last_step=operator.totp_last_step)
        if step is not None:
            operator.totp_last_step = step
            operator.mfa_failed_count = 0
            operator.locked_until = None
            await self.session.flush()
            return True

        if await self._consume_recovery_code(operator, code):
            return True

        operator.mfa_failed_count += 1
        if operator.mfa_failed_count >= MAX_FAILED_ATTEMPTS:
            operator.locked_until = datetime.now(UTC) + LOCKOUT_DURATION
            logger.warning(
                "Konsolen-Anmeldung für %s nach %d Fehlversuchen gesperrt bis %s.",
                operator.upn,
                operator.mfa_failed_count,
                operator.locked_until.isoformat(),
            )
        await self.session.flush()
        return False

    async def _consume_recovery_code(self, operator: ConsoleOperator, code: str) -> bool:
        """Einen Einmal-Code einlösen und aus der Liste entfernen."""
        candidate = totp.normalize_recovery_code(code)
        remaining: list[str] = []
        used = False
        for stored in operator.recovery_codes:
            if used:
                remaining.append(stored)
                continue
            try:
                _hasher.verify(stored, candidate)
            except (VerifyMismatchError, VerificationError):
                remaining.append(stored)
                continue
            used = True
        if not used:
            return False
        # Neu zugewiesen und nicht in der Liste geändert: eine JSONB-Spalte,
        # die man an ihrer Stelle mutiert, merkt SQLAlchemy nicht.
        operator.recovery_codes = remaining
        operator.mfa_failed_count = 0
        operator.locked_until = None
        await self.session.flush()
        logger.warning(
            "Konsolen-Anmeldung für %s über einen Wiederherstellungscode; %d übrig.",
            operator.upn,
            len(remaining),
        )
        return True

    async def confirm_enrolment(self, operator: ConsoleOperator) -> None:
        operator.totp_confirmed_at = datetime.now(UTC)
        await self.session.flush()
        logger.info("Zweiter Faktor für %s bestätigt.", operator.upn)

    async def start_session(
        self,
        operator: ConsoleOperator,
        *,
        fingerprint: str,
        ip: str | None,
        user_agent: str | None,
    ) -> ConsoleSession:
        row = ConsoleSession(
            id=secrets.token_urlsafe(32),
            operator_id=operator.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.console_session_minutes),
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
            spki_fingerprint=fingerprint,
        )
        self.session.add(row)
        operator.last_login_at = datetime.now(UTC)
        await self.session.flush()
        logger.info("Konsolen-Sitzung für %s bis %s.", operator.upn, row.expires_at.isoformat())
        return row

    async def resolve_session(
        self, session_id: str, *, fingerprint: str | None
    ) -> tuple[ConsoleSession, ConsoleOperator] | None:
        """Sitzung und Operator zu einem Cookie — oder `None`.

        Der Fingerprint wird **gegengeprüft**: ein gestohlener Cookie allein
        nützt nichts, wenn das Zertifikat nicht dasselbe ist. Das ist der
        Grund, aus dem er an der Sitzung steht.
        """
        row = await self.session.get(ConsoleSession, session_id)
        if row is None:
            return None
        if row.expires_at <= datetime.now(UTC):
            await self.session.delete(row)
            await self.session.flush()
            return None
        if fingerprint is not None and row.spki_fingerprint != fingerprint:
            logger.warning(
                "Konsolen-Cookie mit fremdem Zertifikat vorgelegt (Sitzung %s).",
                session_id[:8],
            )
            return None
        operator = await self.session.get(ConsoleOperator, row.operator_id)
        if operator is None or not operator.enabled:
            return None
        row.last_seen_at = datetime.now(UTC)
        await self.session.flush()
        return row, operator

    async def end_session(self, session_id: str) -> None:
        row = await self.session.get(ConsoleSession, session_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()


__all__ = [
    "LOCKOUT_DURATION",
    "MAX_FAILED_ATTEMPTS",
    "TOTP_ISSUER",
    "AuthStage",
    "ConsoleAuthError",
    "ConsoleAuthService",
    "Enrolment",
    "fingerprint_from_header",
]
