"""Globale Vorlagen: pflegen, ausliefern (ADR-0018).

Drei Dinge passieren hier, und jedes davon hat einen Entscheid hinter sich:

* **Speichern.** Die Version steigt nur bei einer inhaltlichen Änderung
  (ADR-0018 D4). Wer die Zielgruppe umstellt, hat den Text nicht geändert —
  und der Hinweis „neue globale Fassung" darf beim Kunden nicht aufleuchten,
  weil in der Konsole jemand ein Häkchen verschoben hat.
* **Auflösen.** Welche Vorlagen für einen Kunden gelten, entscheidet die
  Konsole (ADR-0018 D5). Im Soll-Zustand steht nur das Ergebnis.
* **Prüfen.** Der Rumpf muss sich rendern lassen, bevor er ausgeliefert wird.
  Eine Vorlage mit einem Jinja-Fehler würde beim Kunden erst auffallen, wenn
  jemand einen Brief drucken will — und dann bei ihm, nicht hier.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models.template import PlatformTemplate, PlatformTemplateTenant, TemplateAudience
from cockpit_api.models.tenant import Tenant, TenantProfile

#: Die Vorlagen-Schlüssel der Datenebene
#: (`magister_api.services.document_templates.EDITABLE_KEYS`). Bewusst
#: dieselben Namen; ein Test hält die beiden Listen zusammen, damit eine
#: Umbenennung dort hier auffällt und nicht in einer stillen Nicht-Zuordnung
#: endet.
TEMPLATE_KEYS: frozenset[str] = frozenset({"enrollment", "class_change", "password_handout"})

#: Dieselben vier Sprachen wie in der Oberfläche des Kunden.
LANGUAGES: frozenset[str] = frozenset({"de", "fr", "it", "en"})

#: Was in einem Rumpf nichts zu suchen hat. Die Datenebene rendert in einer
#: Jinja-Sandbox — ein `<script>` käme also nie zur Ausführung, wo es Schaden
#: anrichtet. Es hat trotzdem nichts in einem Brief zu suchen, und ein Fund
#: hier ist ein Hinweis darauf, dass jemand HTML aus einer fremden Quelle
#: eingefügt hat.
FORBIDDEN_IN_BODY = re.compile(r"<\s*(script|iframe|object|embed)\b", re.I)


class TemplateError(ValueError):
    """Eine Vorlage, die so nicht gespeichert werden darf."""


def validate_body(key: str, language: str, body_html: str) -> None:
    if key not in TEMPLATE_KEYS:
        raise TemplateError(
            f"'{key}' ist kein Vorlagen-Schlüssel. Erlaubt sind: "
            f"{', '.join(sorted(TEMPLATE_KEYS))}."
        )
    if language not in LANGUAGES:
        raise TemplateError(
            f"'{language}' ist keine unterstützte Sprache. Erlaubt sind: "
            f"{', '.join(sorted(LANGUAGES))}."
        )
    if not body_html.strip():
        raise TemplateError(
            "Der Rumpf ist leer. Eine leere Vorlage würde einen leeren Brief geben."
        )
    found = FORBIDDEN_IN_BODY.search(body_html)
    if found:
        raise TemplateError(
            f"Der Rumpf enthält <{found.group(1)}>. Ein Brief ist ein Dokument, kein Programm."
        )


class TemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, language: str) -> PlatformTemplate | None:
        stmt = select(PlatformTemplate).where(
            PlatformTemplate.key == key, PlatformTemplate.language == language
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> list[PlatformTemplate]:
        stmt = select(PlatformTemplate).order_by(PlatformTemplate.key, PlatformTemplate.language)
        return list((await self.session.execute(stmt)).scalars().all())

    async def tenant_ids(self, template_id: int) -> list[UUID]:
        stmt = select(PlatformTemplateTenant.tenant_id).where(
            PlatformTemplateTenant.platform_template_id == template_id
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def save(
        self,
        *,
        key: str,
        language: str,
        subject: str | None,
        body_html: str,
        may_override: bool,
        audience: TemplateAudience,
        audience_profile: TenantProfile | None,
        tenant_ids: list[UUID] | None,
        is_active: bool,
        actor: str,
    ) -> PlatformTemplate:
        validate_body(key, language, body_html)
        if (audience is TemplateAudience.profile) != (audience_profile is not None):
            raise TemplateError(
                "Ein Profil gehört zu `audience = profile` — und nur dorthin. "
                "Sonst stünde in der Zeile ein Profil, das niemand anwendet."
            )
        if audience is TemplateAudience.selection and not tenant_ids:
            raise TemplateError(
                "Eine Auswahl ohne Kunden erreicht niemanden. Wer eine Vorlage "
                "vorübergehend zurückziehen will, schaltet sie aus (`is_active`)."
            )
        if tenant_ids:
            await self._require_known_tenants(tenant_ids)

        row = await self.get(key, language)
        if row is None:
            row = PlatformTemplate(key=key, language=language, version=1)
            self.session.add(row)
        else:
            # Nur Inhalt zählt (ADR-0018 D4). `is_active` und die Zielgruppe
            # entscheiden, WER die Vorlage bekommt — nicht, was sie sagt.
            content_changed = (
                row.subject != subject
                or row.body_html != body_html
                or row.may_override != may_override
            )
            if content_changed:
                row.version += 1

        row.subject = subject
        row.body_html = body_html
        row.may_override = may_override
        row.audience = audience
        row.audience_profile = audience_profile
        row.is_active = is_active
        row.updated_by = actor
        await self.session.flush()

        if tenant_ids is not None:
            await self._set_selection(row.id, tenant_ids)
        elif audience is not TemplateAudience.selection:
            # Die Zielgruppe ist nicht mehr „Auswahl": die alte Auswahl
            # aufräumen. Sonst läge sie da und würde beim Zurückschalten
            # stillschweigend wieder gelten — mit einem Stand, den seit Monaten
            # niemand gesehen hat.
            await self._set_selection(row.id, [])
        await self.session.refresh(row)
        return row

    async def delete(self, key: str, language: str) -> bool:
        row = await self.get(key, language)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def for_tenant(self, tenant: Tenant) -> list[PlatformTemplate]:
        """Die Vorlagen, die für diesen Kunden gelten (ADR-0018 D5).

        Eine Abfrage und keine Schleife über alle Vorlagen: bei zwanzig
        Vorlagen ist das gleichgültig, aber die Auswahl-Zugehörigkeit steht in
        einer zweiten Tabelle, und die in Python zu verbinden wäre der Anfang
        eines N+1.
        """
        selected = select(PlatformTemplateTenant.platform_template_id).where(
            PlatformTemplateTenant.tenant_id == tenant.id
        )
        stmt = (
            select(PlatformTemplate)
            .where(
                PlatformTemplate.is_active.is_(True),
                (PlatformTemplate.audience == TemplateAudience.all)
                | (
                    (PlatformTemplate.audience == TemplateAudience.profile)
                    & (PlatformTemplate.audience_profile == tenant.profile)
                )
                | (
                    (PlatformTemplate.audience == TemplateAudience.selection)
                    & PlatformTemplate.id.in_(selected)
                ),
            )
            .order_by(PlatformTemplate.key, PlatformTemplate.language)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def desired_templates(self, tenant: Tenant) -> list[dict[str, Any]]:
        """Der Teil des Soll-Zustands, den die Datenebene materialisiert.

        Die Liste ist **vollständig** (ADR-0018 D6): was nicht darin steht,
        wird beim Kunden entfernt. Eine leere Liste heisst deshalb „keine
        Plattformvorlagen" und nicht „keine Aussage" — der Unterschied liegt
        beim Abholer darin, ob der Schlüssel überhaupt da ist.
        """
        return [
            {
                "key": row.key,
                "language": row.language,
                "subject": row.subject,
                "body_html": row.body_html,
                "may_override": row.may_override,
                "version": row.version,
            }
            for row in await self.for_tenant(tenant)
        ]

    async def _require_known_tenants(self, tenant_ids: list[UUID]) -> None:
        stmt = select(Tenant.id).where(Tenant.id.in_(tenant_ids))
        known = set((await self.session.execute(stmt)).scalars().all())
        missing = [str(t) for t in tenant_ids if t not in known]
        if missing:
            raise TemplateError(f"Unbekannte Kunden in der Auswahl: {', '.join(sorted(missing))}.")

    async def _set_selection(self, template_id: int, tenant_ids: list[UUID]) -> None:
        await self.session.execute(
            delete(PlatformTemplateTenant).where(
                PlatformTemplateTenant.platform_template_id == template_id
            )
        )
        for tenant_id in dict.fromkeys(tenant_ids):
            self.session.add(
                PlatformTemplateTenant(platform_template_id=template_id, tenant_id=tenant_id)
            )
        await self.session.flush()


__all__ = [
    "FORBIDDEN_IN_BODY",
    "LANGUAGES",
    "TEMPLATE_KEYS",
    "TemplateError",
    "TemplateService",
    "validate_body",
]
