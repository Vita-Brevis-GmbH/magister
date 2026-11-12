"""Bestehende Konten einer Zielgruppe zuordnen.

Für Konten aus der Zeit vor den Zielgruppen, aus einem Import oder nach einem
Stufenwechsel. Pro Konto:

* **Gruppen**: die der neuen Zielgruppe kommen dazu; die der bisherigen fallen
  weg. Kennt Magister die bisherige Zielgruppe nicht (alte Konten), gelten die
  Gruppen aller *Standard*-Zielgruppen des Standorts als "bisherig" (Zyklus
  1/2/3, Lehrperson, Mitarbeiter:in) — so verliert ein Kind beim Wechsel von
  Zyklus 2 nach 3 die Zyklus-2-Gruppen, behält aber Gruppen aus Zusatz-
  Zielgruppen wie "Tool-X Zugang" und von Hand gesetzte.
* **Konto-Einstellungen** (optional): "darf nicht ändern", "läuft nie ab" und
  der Tresor-Schalter werden übernommen. "Bei erster Anmeldung ändern" nicht:
  bei einem bestehenden Konto hiesse das, die Person beim nächsten Login zu
  einem neuen Passwort zu zwingen — das ist ein Reset, keine Zuordnung.
* **Ablage-OU** bleibt. Passt die Kontoart der Zielgruppe nicht zum Konto
  oder liegt es nicht in ihrer eigenen Ziel-OU, meldet das Ergebnis
  ``ou_unchanged`` — das Verschieben im AD kann der Connector (noch) nicht.

Gruppen schreibt :class:`UserGroupsService` (best-effort, auditiert); dazu
kommt ein eigenes Audit-Event ``zielgruppe_assigned`` je Konto.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.group_template import GroupTemplate
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.group_templates import GroupTemplateRepository
from magister_api.services.password_vault import PasswordVaultService, password_stays
from magister_api.services.user_groups import UserGroupsService, UserNotInAdError
from magister_api.services.zielgruppen import VORGABEN


class ZielgruppeNotFoundError(LookupError):
    pass


@dataclass
class AssignResult:
    ad_object_guid: str
    ok: bool
    error: str | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    ou_unchanged: bool = False


def _category(kind: str | None) -> str | None:
    """teacher | student | company — die Kontoart ohne Zyklus."""
    if kind is None:
        return None
    if kind.startswith("student"):
        return "student"
    return kind if kind in ("teacher", "company") else None


class ZielgruppenAssignService:
    def __init__(
        self, session: AsyncSession, settings: Settings, scope: ScopeContext, ad: AdClient
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
        self.repo = GroupTemplateRepository(session)
        self.audit = AuditService(session, settings)

    async def assign(
        self,
        *,
        template_id: int,
        guids: list[str],
        apply_settings: bool,
        ip: str | None,
        request_id: str,
    ) -> list[AssignResult]:
        tpl = await self.repo.get(template_id)
        if tpl is None or tpl.status != "active":
            raise ZielgruppeNotFoundError(str(template_id))
        links = (await self.repo.school_ids_for([tpl.id])).get(tpl.id, [])
        results: list[AssignResult] = []
        for guid in dict.fromkeys(guids):
            results.append(
                await self._assign_one(
                    tpl, links, guid, apply_settings=apply_settings, ip=ip, request_id=request_id
                )
            )
        return results

    async def _previous_groups(self, user: AdUserCache) -> set[str]:
        if user.group_template_id is not None:
            prev = await self.repo.get(user.group_template_id)
            if prev is not None:
                return set(prev.ad_groups or [])
        # Unbekannt: alle Standard-Zielgruppen, die am Standort angeboten werden.
        offered = (
            await self.repo.list_for_school(user.school_id)
            if user.school_id is not None
            else await self.repo.list_active()
        )
        out: set[str] = set()
        for t in offered:
            if t.kind in VORGABEN:
                out.update(t.ad_groups or [])
        return out

    async def _assign_one(
        self,
        tpl: GroupTemplate,
        links: list[int],
        guid: str,
        *,
        apply_settings: bool,
        ip: str | None,
        request_id: str,
    ) -> AssignResult:
        # scope-bypass: admin-only endpoint; the objectGUID addresses one account.
        user = (
            await self.session.execute(
                select(AdUserCache).where(AdUserCache.ad_object_guid == guid)
            )
        ).scalar_one_or_none()
        if user is None:
            return AssignResult(guid, ok=False, error="user_not_found")
        if links and user.school_id not in links:
            return AssignResult(guid, ok=False, error="not_for_school")

        new_groups = list(tpl.ad_groups or [])
        current = list(user.ad_groups or [])
        drop = (await self._previous_groups(user)) - set(new_groups)
        desired = [g for g in current if g not in drop] + [
            g for g in new_groups if g not in set(current)
        ]
        previous_template = user.group_template_id
        writer = UserGroupsService(self.session, self.settings, self.scope, self.ad)
        try:
            groups = await writer.set_groups(
                target=user, desired=desired, ip=ip, request_id=request_id
            )
            if apply_settings:
                await self._apply_settings(user, tpl)
            outside_own_ou = await self._outside_own_ou(tpl, user)
        except UserNotInAdError:
            return AssignResult(guid, ok=False, error="user_not_in_ad")
        except AdUnavailableError:
            return AssignResult(guid, ok=False, error="ad_unavailable")

        user.group_template_id = tpl.id
        await self.session.flush()
        ou_unchanged = outside_own_ou or (
            tpl.kind in VORGABEN
            and _category(tpl.kind) is not None
            and _category(tpl.kind) != _category(user.kind)
        )
        await self.audit.emit(
            action="zielgruppe_assigned",
            target_kind="ad_user",
            target_id=guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=user.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "group_template_id": tpl.id,
                "previous_group_template_id": previous_template,
                "added": len(groups.added),
                "removed": len(groups.removed),
                "failed": len(groups.failed),
                "settings_applied": apply_settings,
                "ou_unchanged": ou_unchanged,
            },
        )
        return AssignResult(
            guid,
            ok=True,
            added=groups.added,
            removed=groups.removed,
            failed=groups.failed,
            ou_unchanged=ou_unchanged,
        )

    async def _outside_own_ou(self, tpl: GroupTemplate, user: AdUserCache) -> bool:
        """Hat die Zielgruppe eine eigene Ziel-OU und liegt das Konto woanders?"""
        if not tpl.ad_ou or tpl.kind in VORGABEN:
            # Feste Kontoart: über die OU entscheidet die Kontoart (oben).
            return False
        user_dn = await self.ad.find_user_dn(user.ad_object_guid)
        if not user_dn:
            raise UserNotInAdError(user.ad_object_guid)
        return not user_dn.lower().endswith("," + tpl.ad_ou.lower())

    async def _apply_settings(self, user: AdUserCache, tpl: GroupTemplate) -> None:
        """ "Darf nicht ändern", "läuft nie ab" und Tresor nach der Zielgruppe."""
        need_dn = (
            user.password_never_expires != tpl.password_never_expires
            or user.cannot_change_password != tpl.cannot_change_password
        )
        if need_dn:
            user_dn = await self.ad.find_user_dn(user.ad_object_guid)
            if not user_dn:
                raise UserNotInAdError(user.ad_object_guid)
            if user.password_never_expires != tpl.password_never_expires:
                await self.ad.set_password_never_expires(
                    user_dn=user_dn, value=tpl.password_never_expires
                )
                user.password_never_expires = tpl.password_never_expires
            if user.cannot_change_password != tpl.cannot_change_password:
                await self.ad.set_cannot_change_password(
                    user_dn=user_dn, value=tpl.cannot_change_password
                )
                user.cannot_change_password = tpl.cannot_change_password
        # Tresor nur, wenn das Passwort so bleibt — sonst veraltet die Kopie.
        # "Bei erster Anmeldung ändern" wird hier nicht gesetzt, zählt also
        # nicht. Das Passwort selbst kennt Magister hier nicht; es kommt mit
        # dem nächsten Reset oder dem Passwort-Import in den Tresor.
        store = tpl.store_password and password_stays(
            force_change=False,
            cannot_change_password=tpl.cannot_change_password,
            password_never_expires=tpl.password_never_expires,
        )
        if user.store_password and not store:
            await PasswordVaultService(self.session, self.settings).clear(user.ad_object_guid)
        user.store_password = store


__all__ = ["AssignResult", "ZielgruppeNotFoundError", "ZielgruppenAssignService"]
