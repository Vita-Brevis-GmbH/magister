"""Rollen nur aus dem Cockpit: der Merker im Kundenschema (ADR-0027).

Führt das Cockpit die Rollen eines Kunden — der Soll-Zustand trägt
``role_assignments`` und nicht ``null`` —, vergibt und entzieht Magister von
Hand keine Rollen mehr, und Anmeldekonten legt nur noch das Cockpit an. Ob das
gilt, steht in ``app_settings.roles_from_cockpit``:

* **Gesetzt vom Abgleich** (:func:`set_roles_from_cockpit`), bei jedem Lauf aus
  dem Soll-Zustand. Der liegt nur im Speicher des Abgleichs; die API fragt den
  Merker, damit die Sperre auch nach einem Neustart und in jedem Container gilt.
* **Gelesen von der API** (:func:`roles_from_cockpit`) bei jeder Änderung an
  Rollen und Anmeldekonten (``auth.role_lock``) und von der Zustandsmeldung
  (``rollen_fremd`` nur, solange der Merker steht).

Sagt das Cockpit nichts mehr (``null``), fällt der Merker, und die Vergabe von
Hand geht wieder — sonst blieben Zuweisungen stehen, die niemand mehr entfernen
kann (ADR-0026 D5).
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings

logger = logging.getLogger(__name__)

#: Audit-Ereignis, wenn das Cockpit die Rollen übernimmt oder abgibt.
ROLES_SOURCE_EVENT = "roles_source_changed"


async def roles_from_cockpit(session: AsyncSession) -> bool:
    """Führt das Cockpit die Rollen dieses Kunden?

    `# scope-bypass: app_settings ist ein Singleton je Kundenschema ohne
    Schul-Scope; die Mandantentrennung leistet der ``search_path``.`
    """
    stmt = select(AppSettings.roles_from_cockpit).where(AppSettings.id == 1)
    return bool(await session.scalar(stmt))


async def set_roles_from_cockpit(
    session: AsyncSession,
    settings: Settings,
    value: bool,
    *,
    actor: str,
    request_id: str,
    tenant_slug: str,
) -> bool:
    """Den Merker setzen; ``True``, wenn er sich geändert hat.

    Nur die Änderung schreibt (Zeile und Audit) — der Abgleich läuft alle paar
    Minuten, und ein Lauf ohne Änderung soll nichts hinterlassen (ADR-0017 D4).
    Ein bedingtes ``UPDATE … RETURNING`` statt Lesen und Schreiben: gleichen
    zwei Container zugleich ab, wartet der zweite auf die Zeilensperre, findet
    danach nichts mehr zu ändern und schreibt kein zweites Audit-Ereignis.

    `# scope-bypass: app_settings ist ein Singleton je Kundenschema.`
    """
    stmt = (
        update(AppSettings)
        .where(AppSettings.id == 1, AppSettings.roles_from_cockpit.is_distinct_from(value))
        .values(roles_from_cockpit=value)
        .returning(AppSettings.id)
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        return False
    await AuditService(session, settings).emit(
        action=ROLES_SOURCE_EVENT,
        target_kind="app_settings",
        target_id="roles_from_cockpit",
        actor_upn=actor,
        actor_object_guid=None,
        school_id=None,
        ip=None,
        request_id=request_id[:36],
        payload={"from_cockpit": value},
    )
    logger.info(
        "Rollen von %s %s",
        tenant_slug,
        "führt jetzt das Cockpit" if value else "führt das Cockpit nicht mehr",
    )
    return True


__all__ = ["ROLES_SOURCE_EVENT", "roles_from_cockpit", "set_roles_from_cockpit"]
