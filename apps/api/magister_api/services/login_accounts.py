"""Anmeldekonten aus dem Keycloak-Realm des Kunden (ADR-0025).

Keycloak verwaltet die Benutzer, Magister nur die Autorisierung. Dieser Dienst
ordnet eine Anmeldung einem Konto zu und führt die Handgriffe der
Admin-Oberfläche aus (vorab anlegen, sperren, Bindung lösen, löschen).

Die Zuordnung bei der Anmeldung, in dieser Reihenfolge:

1. Treffer über ``issuer`` + ``subject`` → dieses Konto.
2. Sonst ein Konto mit diesem ``username`` ohne gebundenes ``subject`` (vorab
   angelegt) → das ``subject`` wird gebunden.
3. ``username`` vorhanden, aber an ein **anderes** ``subject`` gebunden →
   abweisen. Ein Benutzername, den Keycloak neu vergeben hat, übernimmt nie
   still die Rechte des früheren Kontos.
4. Sonst ein neues Konto. ``principal_guid`` ist die objectGUID der Zeile in
   ``ad_user_cache`` mit ``upn == username`` (die Lehrperson behält Klassen und
   Rollen) oder eine stabile GUID aus dem Benutzernamen
   (:func:`synthetic_principal`), so dass vorab vergebene Rollen passen.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.bootstrap import is_bootstrap_admin
from magister_api.auth.oidc import OidcUserInfo
from magister_api.config import Settings
from magister_api.models.auth import LoginAccount
from magister_api.models.base import utcnow
from magister_api.repositories.auth import (
    AdUserCacheRepository,
    LoginAccountRepository,
    SessionRepository,
)
from magister_api.schemas.common import validate_login_name

logger = logging.getLogger(__name__)

#: Fester Namensraum für :func:`synthetic_principal`. Er darf sich nie ändern:
#: an der daraus abgeleiteten GUID hängen Rollen, die vor der ersten Anmeldung
#: vergeben wurden. Wer dieselbe GUID ausserhalb von Magister berechnen muss
#: (etwa das Cockpit), nimmt genau diesen Wert und genau dieses Präfix.
PRINCIPAL_NAMESPACE = uuid.UUID("e5df4e2c-4a65-4cbf-ae9d-7ea9a4e53044")
PRINCIPAL_PREFIX = "magister-konto:"


def synthetic_principal(username: str) -> str:
    """Stabile GUID eines Kontos ohne AD-Zeile: ``uuid5(Namensraum, Präfix + Name)``."""
    return str(uuid.uuid5(PRINCIPAL_NAMESPACE, PRINCIPAL_PREFIX + username.strip().lower()))


class LoginRefusedError(Exception):
    """A successful OIDC handshake that must not yield a session.

    ``code`` is the reason the login page translates (``auth.oidc_errors.*``).
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LoginAccountConflictError(Exception):
    """An admin action on a login account that cannot be carried out."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AccountResolution:
    account: LoginAccount
    #: Bei dieser Anmeldung neu angelegt.
    created: bool
    #: Ein vorab angelegtes Konto, das bei dieser Anmeldung sein ``subject`` bekam.
    bound: bool


class LoginAccountService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = LoginAccountRepository(session)

    async def principal_for(self, username: str) -> str:
        """objectGUID der AD-Zeile mit ``upn == username``, sonst die synthetische GUID."""
        row = await AdUserCacheRepository(self.session).find_by_upn(username)
        if row is not None:
            return row.ad_object_guid
        return synthetic_principal(username)

    async def resolve_for_login(self, userinfo: OidcUserInfo) -> AccountResolution:
        """Das Konto zu dieser Anmeldung finden, binden oder anlegen (Regeln oben)."""
        account = await self.repo.get_by_subject(issuer=userinfo.issuer, subject=userinfo.subject)
        if account is not None:
            await self._follow_username(account, userinfo.username)
            return AccountResolution(account=account, created=False, bound=False)

        account = await self.repo.get_by_username(userinfo.username)
        if account is not None:
            if account.subject is not None:
                raise LoginRefusedError("account_bound_to_other_subject")
            if not account.enabled:
                # Ein gesperrtes Konto wird gar nicht erst gebunden.
                raise LoginRefusedError("account_disabled")
            account.issuer = userinfo.issuer
            account.subject = userinfo.subject
            await self.session.flush()
            return AccountResolution(account=account, created=False, bound=True)

        principal = await self.principal_for(userinfo.username)
        if await self.repo.get_by_principal(principal) is not None:
            # Ein anderes Konto hält schon diese GUID — typisch: dieselbe
            # Person mit neuem Benutzernamen und neu angelegtem
            # Keycloak-Benutzer. Wer welches Konto ist, entscheidet ein Mensch
            # (altes Konto löschen oder lösen), nicht diese Funktion.
            raise LoginRefusedError("account_principal_conflict")
        account = await self.repo.add(
            LoginAccount(
                issuer=userinfo.issuer,
                subject=userinfo.subject,
                username=userinfo.username,
                display_name=userinfo.display_name,
                email=userinfo.email,
                principal_guid=principal,
                enabled=True,
                created_at=utcnow(),
            )
        )
        return AccountResolution(account=account, created=True, bound=False)

    async def _follow_username(self, account: LoginAccount, username: str) -> None:
        """Einem in Keycloak umbenannten Benutzer folgen — wenn der Name frei ist.

        Ist der neue Name schon an ein anderes Konto vergeben (vorab angelegt
        oder ein früheres), bleibt der alte stehen: die Identität ist das
        ``subject``, und ein fremdes Konto zu überschreiben wäre schlimmer als
        eine veraltete Anzeige.
        """
        if account.username == username:
            return
        if await self.repo.get_by_username(username) is not None:
            logger.warning(
                "Anmeldekonto %s: neuer Benutzername ist schon vergeben, alter bleibt",
                account.id,
            )
            return
        account.username = username
        await self.session.flush()

    @staticmethod
    def note_login(account: LoginAccount, userinfo: OidcUserInfo) -> None:
        """Anzeige und Zeitpunkt nachführen (Keycloak ist die Quelle)."""
        if userinfo.display_name:
            account.display_name = userinfo.display_name
        if userinfo.email:
            account.email = userinfo.email
        account.last_login_at = utcnow()

    # ---------- Admin-Oberfläche ----------

    async def precreate(self, *, username: str, display_name: str | None) -> LoginAccount:
        """Ein Konto vorab anlegen, damit Rollen vor der ersten Anmeldung vergeben werden können."""
        name = validate_login_name(username)
        if await self.repo.get_by_username(name) is not None:
            raise LoginAccountConflictError("login_account_exists")
        principal = await self.principal_for(name)
        if await self.repo.get_by_principal(principal) is not None:
            raise LoginAccountConflictError("account_principal_conflict")
        return await self.repo.add(
            LoginAccount(
                issuer=None,
                subject=None,
                username=name,
                display_name=(display_name or "").strip()[:200] or None,
                email=None,
                principal_guid=principal,
                enabled=True,
                created_at=utcnow(),
            )
        )

    async def set_enabled(self, account: LoginAccount, *, enabled: bool) -> int:
        """Sperren oder freigeben. Sperren beendet die laufenden Sitzungen."""
        if not enabled and is_bootstrap_admin(self.settings, account.username):
            raise LoginAccountConflictError("login_account_is_bootstrap_admin")
        account.enabled = enabled
        await self.session.flush()
        if enabled:
            return 0
        return await SessionRepository(self.session).delete_oidc_for(account.principal_guid)

    async def unbind(self, account: LoginAccount) -> int:
        """Die Bindung an ``issuer`` + ``subject`` lösen.

        Für einen in Keycloak neu angelegten Benutzer mit demselben Namen oder
        einen Wechsel des Realms: die nächste Anmeldung mit diesem
        Benutzernamen bindet neu. Rollen bleiben, laufende Sitzungen enden.
        """
        account.issuer = None
        account.subject = None
        await self.session.flush()
        return await SessionRepository(self.session).delete_oidc_for(account.principal_guid)

    async def delete(self, account: LoginAccount) -> int:
        """Das Konto löschen. Rollen hängen an der GUID und bleiben stehen."""
        if is_bootstrap_admin(self.settings, account.username):
            raise LoginAccountConflictError("login_account_is_bootstrap_admin")
        ended = await SessionRepository(self.session).delete_oidc_for(account.principal_guid)
        await self.session.delete(account)
        await self.session.flush()
        return ended


__all__ = [
    "PRINCIPAL_NAMESPACE",
    "PRINCIPAL_PREFIX",
    "AccountResolution",
    "LoginAccountConflictError",
    "LoginAccountService",
    "LoginRefusedError",
    "synthetic_principal",
]
