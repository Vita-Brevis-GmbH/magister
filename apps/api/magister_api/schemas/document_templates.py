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


__all__ = [
    "DocumentTemplateListOut",
    "DocumentTemplateMetaOut",
    "DocumentTemplateStarter",
    "DocumentTemplateOut",
    "DocumentTemplatePreviewOut",
    "DocumentTemplatePreviewRequest",
    "DocumentTemplateSave",
]
