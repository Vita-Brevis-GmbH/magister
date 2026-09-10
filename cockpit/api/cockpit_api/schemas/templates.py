"""Schemata für die globalen Vorlagen (ADR-0018)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cockpit_api.models.template import TemplateAudience
from cockpit_api.models.tenant import TenantProfile


class PlatformTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    language: str
    subject: str | None
    body_html: str
    may_override: bool
    version: int
    audience: TemplateAudience
    audience_profile: TenantProfile | None
    is_active: bool
    #: Bei `audience = selection` die gewählten Kunden, sonst leer. Als eigenes
    #: Feld und nicht in `audience`: eine Oberfläche, die die Auswahl anzeigen
    #: will, soll dafür nicht eine zweite Anfrage brauchen.
    tenant_ids: list[UUID] = []
    updated_at: datetime
    updated_by: str | None


class PlatformTemplateSave(BaseModel):
    subject: str | None = Field(default=None, max_length=512)
    body_html: str
    may_override: bool = True
    audience: TemplateAudience = TemplateAudience.all
    audience_profile: TenantProfile | None = None
    #: `null` heisst „Auswahl nicht anfassen"; `[]` heisst „Auswahl leeren".
    #: Der Unterschied ist derselbe wie bei `clear_rbac` in den Einstellungen —
    #: ohne ihn gäbe es keinen Weg zurück.
    tenant_ids: list[UUID] | None = None
    is_active: bool = True
    actor: str = Field(min_length=1, max_length=320)


class PlatformTemplateListOut(BaseModel):
    items: list[PlatformTemplateOut]
    #: Die Schlüssel und Sprachen, die es gibt — damit die Oberfläche die
    #: Auswahl nicht doppelt pflegt.
    keys: list[str]
    languages: list[str]


__all__ = ["PlatformTemplateListOut", "PlatformTemplateOut", "PlatformTemplateSave"]
