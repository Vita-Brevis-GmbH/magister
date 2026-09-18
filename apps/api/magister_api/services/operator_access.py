"""Einen Operator-Einlöseschein gegen eine Sitzung tauschen (ADR-0019).

Was hier passiert, ist die eine Stelle, an der ein Mensch von Vita Brevis in
das Schema eines Kunden kommt. Deshalb macht sie vier Dinge und nicht drei:

1. Sie prüft den Schein (Signatur, Mandant, Ablauf, Höchstdauer).
2. Sie verbraucht ihn **einmal** — über den Primärschlüssel, nicht über eine
   Abfrage. Zwei gleichzeitige Einlösungen sind sonst beide erfolgreich.
3. Sie legt die Sitzung an, befristet, mit `auth_kind = "operator"` und ohne
   irgendeine Spur in den Personendaten des Kunden.
4. Sie schreibt ein Audit-Ereignis in das Protokoll des Kunden — mit dem
   Grund, wie er in der signierten Assertion stand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.operator_assertion import (
    OperatorAssertion,
    OperatorAssertionError,
    parse_and_verify,
)
from magister_api.auth.sessions import new_session_id
from magister_api.config import Settings
from magister_api.models.base import utcnow
from magister_api.models.operator_access import OperatorAccess
from magister_api.repositories.auth import SessionRepository

logger = logging.getLogger(__name__)


class AssertionAlreadyRedeemedError(OperatorAssertionError):
    """Derselbe Schein ein zweites Mal. Abgewiesen."""


@dataclass(frozen=True)
class RedeemedAccess:
    session_id: str
    access: OperatorAccess
    assertion: OperatorAssertion


class OperatorAccessService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def redeem(
        self,
        raw_assertion: str,
        *,
        tenant_slug: str,
        ip: str | None,
        user_agent: str | None,
        request_id: str,
    ) -> RedeemedAccess:
        assertion = parse_and_verify(
            raw_assertion,
            self.settings.operator_public_key,
            tenant_slug=tenant_slug,
        )

        session_id = new_session_id()
        now = datetime.now(UTC)
        lifetime = timedelta(minutes=self.settings.operator_session_minutes)
        access = OperatorAccess(
            jti=assertion.jti,
            operator_upn=assertion.operator,
            reason=assertion.reason,
            ticket=assertion.ticket,
            #: Nur der Anfang der Session-Id — der Rest ist das Cookie.
            session_ref=session_id[:12],
            started_at=now,
            expires_at=now + lifetime,
            ip=ip,
        )
        self.session.add(access)
        try:
            # Der Zugriffseintrag zuerst, und ausdrücklich mit eigenem
            # `flush`: schlägt der Primärschlüssel an, gibt es **keine**
            # Sitzung. Umgekehrt wäre die Reihenfolge falsch — dann existierte
            # die Sitzung, bevor klar ist, ob der Schein noch frei war.
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            logger.warning(
                "Operator-Einlöseschein %s wurde erneut vorgelegt (Kunde %s, IP %s).",
                assertion.jti,
                tenant_slug,
                ip or "—",
            )
            raise AssertionAlreadyRedeemedError(
                "Dieser Einlöseschein ist bereits verbraucht."
            ) from exc

        await SessionRepository(self.session).create(
            session_id=session_id,
            # Kein Benutzer des Kunden (ADR-0019 D5): die Spalte ist nicht
            # nullable, und ein erfundener GUID wäre schlimmer als ein leerer
            # Wert — er sähe in jeder Abfrage wie ein echter aus.
            ad_object_guid="",
            oidc_subject="",
            lifetime=lifetime,
            ip=ip,
            user_agent=user_agent,
            auth_kind="operator",
            operator_upn=assertion.operator,
            operator_jti=assertion.jti,
        )
        await AuditService(self.session, self.settings).emit(
            action="operator_access_started",
            target_kind="operator_access",
            target_id=str(assertion.jti),
            actor_upn=assertion.operator,
            actor_object_guid=None,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={
                "reason": assertion.reason,
                "ticket": assertion.ticket,
                "until": access.expires_at.isoformat(),
            },
        )
        logger.info(
            "Operator-Zugriff auf %s durch %s bis %s: %s",
            tenant_slug,
            assertion.operator,
            access.expires_at.isoformat(),
            assertion.reason,
        )
        return RedeemedAccess(session_id=session_id, access=access, assertion=assertion)

    async def end(
        self,
        *,
        jti: object,
        ip: str | None,
        request_id: str,
        actor_upn: str,
    ) -> None:
        """Den Zugriff als beendet vermerken (ADR-0019 D6).

        Ein abgelaufener und ein beendeter Zugriff sind für den Kunden nicht
        dasselbe — deshalb ein eigener Zeitstempel und nicht nur der Ablauf.

        `# scope-bypass: Operator-Zugriffe sind mandantenweit und tragen keine
        Personendaten des Kunden; die Trennung leistet der ``search_path``.`
        """
        row = await self.session.get(OperatorAccess, jti)
        if row is None or row.ended_at is not None:
            return
        row.ended_at = utcnow()
        await self.session.flush()
        await AuditService(self.session, self.settings).emit(
            action="operator_access_ended",
            target_kind="operator_access",
            target_id=str(jti),
            actor_upn=actor_upn,
            actor_object_guid=None,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={"started_at": row.started_at.isoformat()},
        )

    async def active(self) -> OperatorAccess | None:
        """Der laufende Zugriff, wenn es einen gibt — für den Hinweisbalken.

        `# scope-bypass: siehe `end`.`
        """
        stmt = (
            select(OperatorAccess)
            .where(OperatorAccess.ended_at.is_(None), OperatorAccess.expires_at > utcnow())
            .order_by(OperatorAccess.started_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def history(self, limit: int = 100) -> list[OperatorAccess]:
        """Die Liste für den Kunden (ADR-0019 D6).

        `# scope-bypass: siehe `end`.`
        """
        stmt = (
            select(OperatorAccess).order_by(OperatorAccess.started_at.desc()).limit(min(limit, 500))
        )
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = ["AssertionAlreadyRedeemedError", "OperatorAccessService", "RedeemedAccess"]
