"""Schemas for the document-template admin surface (M6 Feature B)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Guard against pathological payloads while allowing rich HTML letters.
_MAX_BODY = 100_000


class DocumentTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    language: str
    school_id: int | None
    subject: str | None
    body_html: str
    is_active: bool
    updated_by: str | None
    updated_at: datetime
    #: Die Fassung, die der Kunde zur Kenntnis genommen hat (ADR-0018 D4).
    platform_version_ack: int | None = None
    #: Es gibt eine neuere gelieferte Fassung als die quittierte. Ausgerechnet
    #: und nicht vom Frontend zusammengesetzt: der Vergleich ist die Regel, und
    #: die gehört an eine Stelle.
    platform_update_available: bool = False
    #: Diese eigene Fassung gilt derzeit **nicht**, weil die Plattformfassung
    #: gesperrt ist. Sie bleibt liegen und wird nicht gelöscht (ADR-0018 D3).
    superseded_by_platform: bool = False


class PlatformTemplateOut(BaseModel):
    """Eine gelieferte Fassung, wie der Kunde sie sieht.

    Mit Text: wer entscheiden soll, ob er seine eigene Fassung aufgibt, muss
    die neue lesen können. Ein Hinweis „es gibt eine neue Fassung" ohne den
    Text wäre eine Aufforderung, in der Konsole nachzufragen.
    """

    model_config = ConfigDict(from_attributes=True)

    key: str
    language: str
    subject: str | None
    body_html: str
    may_override: bool
    version: int
    delivered_at: datetime


class DocumentTemplateSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)
    language: str = Field(max_length=8)
    school_id: int | None = None
    subject: str | None = Field(default=None, max_length=512)
    body_html: str = Field(max_length=_MAX_BODY)
    is_active: bool = True


class DocumentTemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_html: str = Field(max_length=_MAX_BODY)
    subject: str | None = Field(default=None, max_length=512)


class DocumentTemplatePreviewOut(BaseModel):
    subject: str | None
    html: str


class DocumentTemplateStarter(BaseModel):
    subject: str
    body_html: str


class DocumentTemplateMetaOut(BaseModel):
    keys: list[str]
    placeholders: list[str]
    languages: list[str]
    # Built-in starter content per key — the "template for the template".
    starters: dict[str, DocumentTemplateStarter]


class DocumentTemplateListOut(BaseModel):
    templates: list[DocumentTemplateOut]
    meta: DocumentTemplateMetaOut
    #: Die Fassungen des Betreibers. Leer auf einer Einzelinstallation — dort
    #: gibt es keinen Betreiber ausser dem Kunden selbst (ADR-0016 D9).
    platform_templates: list[PlatformTemplateOut] = []


__all__ = [
    "DocumentTemplateListOut",
    "DocumentTemplateMetaOut",
    "DocumentTemplateStarter",
    "DocumentTemplateOut",
    "DocumentTemplatePreviewOut",
    "DocumentTemplatePreviewRequest",
    "DocumentTemplateSave",
    "PlatformTemplateOut",
]
