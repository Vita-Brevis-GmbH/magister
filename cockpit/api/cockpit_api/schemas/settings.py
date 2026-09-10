"""Schemata für die Systemeinstellungen und die Rechte-Matrix (ADR-0017).

Bewusst mit einem freien Dokument (`dict[str, Any]`) und nicht mit vierzig
typisierten Feldern: die Felder gehören der Datenebene, und jedes neue Feld
dort wäre sonst eine Änderung an drei Stellen. Geprüft wird im Dienst gegen
`POLICY_KEYS` — ausdrücklich und mit einer Fehlermeldung, die den Feldnamen
nennt.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlatformSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    defaults: dict[str, Any]
    rbac: dict[str, list[str]]
    updated_at: datetime
    updated_by: str | None


class PlatformSettingsUpdate(BaseModel):
    """Nur Gesetztes wird geändert; `null` heisst „nicht angefasst"."""

    defaults: dict[str, Any] | None = None
    rbac: dict[str, list[str]] | None = None
    actor: str = Field(min_length=1, max_length=320)


class TenantSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    overrides: dict[str, Any]
    rbac: dict[str, list[str]] | None
    #: `null`, solange es für diesen Kunden keine Abweichung gibt. Ein
    #: erfundener Zeitstempel „jetzt" wäre bequemer und würde behaupten,
    #: gerade sei etwas geändert worden.
    updated_at: datetime | None
    updated_by: str | None


class TenantSettingsUpdate(BaseModel):
    overrides: dict[str, Any] | None = None
    rbac: dict[str, list[str]] | None = None
    #: Setzt die eigene Rechte-Matrix zurück, sodass wieder die globale gilt.
    #: Ausdrücklich und nicht über `rbac: null` — `null` heisst „nicht
    #: angefasst", und ohne diesen Unterschied gäbe es keinen Weg zurück.
    clear_rbac: bool = False
    actor: str = Field(min_length=1, max_length=320)


class DesiredTemplateOut(BaseModel):
    """Eine globale Vorlage, wie die Datenebene sie materialisiert (ADR-0018)."""

    key: str
    language: str
    subject: str | None
    body_html: str
    may_override: bool
    version: int


class DesiredStateOut(BaseModel):
    """Was für diesen Kunden gelten soll — die Sicht der Datenebene.

    `*_source` sagt, woher der Stand kommt. Nicht Zierrat: wer sich fragt,
    warum ein Kunde ein anderes Sync-Intervall hat als die übrigen, bekommt
    hier die Antwort ohne einen Blick in die Datenbank.
    """

    settings: dict[str, Any]
    rbac: dict[str, list[str]]
    #: Die **vollständige** Liste der Plattformvorlagen für diesen Kunden
    #: (ADR-0018 D6): was nicht darin steht, wird bei ihm entfernt. Eine leere
    #: Liste heisst „keine" — „keine Aussage" wäre ein fehlendes Feld, und das
    #: kann nur eine ältere Konsole liefern.
    templates: list[DesiredTemplateOut] = []
    settings_source: str
    rbac_source: str


__all__ = [
    "DesiredStateOut",
    "DesiredTemplateOut",
    "PlatformSettingsOut",
    "PlatformSettingsUpdate",
    "TenantSettingsOut",
    "TenantSettingsUpdate",
]
