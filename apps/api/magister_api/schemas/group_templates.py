"""Zielgruppe (``group_templates``) request/response schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PasswordProfile = Literal["readable", "teacher", "complex"]

# Ziel-OU: ein DN unterhalb einer Domäne ("OU=Gäste,DC=schule,DC=local").
_OU_DN_RE = re.compile(r"^(OU|CN)=[^,]+(,(OU|CN)=[^,]+)*(,DC=[^,]+)+$", re.IGNORECASE)


def clean_ou(value: str | None) -> str | None:
    """Leerzeichen um die Kommas weg; "" bleibt "" (= Ziel-OU entfernen)."""
    if value is None:
        return None
    cleaned = ",".join(part.strip() for part in value.strip().split(","))
    if cleaned and not _OU_DN_RE.match(cleaned):
        raise ValueError("ad_ou must be a DN like OU=Name,DC=schule,DC=local")
    return cleaned


class GroupTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, max_length=32)
    ad_groups: list[str] = Field(default_factory=list)
    # Standorte the template is offered at; empty = global (every Standort).
    school_ids: list[int] = Field(default_factory=list)
    password_profile: PasswordProfile = "complex"  # noqa: S105 — Passwortart, kein Passwort
    force_change: bool = True
    cannot_change_password: bool = False
    password_never_expires: bool = False
    store_password: bool = False
    # Ziel-OU (nur bei freier Kontoart wirksam); leer = OU des Standorts.
    ad_ou: str | None = Field(default=None, max_length=512)

    _ou = field_validator("ad_ou")(clean_ou)


class GroupTemplateUpdate(BaseModel):
    """Patch payload — supply only the fields you want to change."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, max_length=32)
    ad_groups: list[str] | None = None
    school_ids: list[int] | None = None
    password_profile: PasswordProfile | None = None
    force_change: bool | None = None
    cannot_change_password: bool | None = None
    password_never_expires: bool | None = None
    store_password: bool | None = None
    # "" entfernt die Ziel-OU, None lässt sie, wie sie ist.
    ad_ou: str | None = Field(default=None, max_length=512)

    _ou = field_validator("ad_ou")(clean_ou)


class GroupTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    kind: str | None
    ad_groups: list[str] = Field(default_factory=list)
    school_ids: list[int] = Field(default_factory=list)
    status: str
    password_profile: str
    force_change: bool
    cannot_change_password: bool
    password_never_expires: bool
    store_password: bool
    ad_ou: str | None = None
    created_at: datetime
    updated_at: datetime


class DefaultsRequest(BaseModel):
    school_id: int


class AssignRequest(BaseModel):
    """Konten einer Zielgruppe zuordnen (einzeln oder als Sammelaktion)."""

    ad_object_guids: list[str] = Field(min_length=1, max_length=500)
    # "Darf nicht ändern", "läuft nie ab" und Tresor übernehmen.
    apply_settings: bool = True


class AssignResultOut(BaseModel):
    ad_object_guid: str
    ok: bool
    error: str | None = None
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    # Kontoart der Zielgruppe passt nicht zum Konto — die OU bleibt.
    ou_unchanged: bool = False


__all__ = [
    "AssignRequest",
    "AssignResultOut",
    "DefaultsRequest",
    "GroupTemplateCreate",
    "GroupTemplateOut",
    "GroupTemplateUpdate",
    "PasswordProfile",
    "clean_ou",
]
