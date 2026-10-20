"""Schemas for admin single-user create/delete + demo-data purge."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from magister_api.schemas.common import Upn
from magister_api.schemas.group_templates import clean_ou


class AdUserCreateRequest(BaseModel):
    given_name: str = Field(min_length=1, max_length=64)
    surname: str = Field(min_length=1, max_length=64)
    sam_account_name: str = Field(min_length=1, max_length=20)
    user_principal_name: Upn
    mail: str | None = Field(default=None, max_length=320)
    ou_key: str = Field(description="teacher | student_zyklus1 | student_zyklus2 | student_zyklus3")
    # Target school — its per-school AD config drives the OU + default groups.
    # Optional: ohne Standort braucht es eine globale Zielgruppe mit eigener
    # Ziel-OU (z. B. "Sonstige"); das Konto gehört dann keinem Standort.
    school_id: int | None = Field(default=None, ge=1)
    # Optionale Zielgruppe — legt Kontoart/OU, Gruppen, Passwortart und
    # Konto-Einstellungen fest (``ou_key`` wird dann von ihr übersteuert). Muss
    # an ``school_id`` angeboten werden (verknüpft oder global).
    group_template_id: int | None = Field(default=None, ge=1)
    # Ziel-OU für dieses Konto. Nur ohne Zielgruppe oder bei einer Zielgruppe
    # ohne feste Kontoart; gewinnt vor deren Ziel-OU. Ohne Standort Pflicht
    # (sonst die der Zielgruppe), mit Standort optional (leer = seine OU).
    ad_ou: str | None = Field(default=None, max_length=512)
    # Optional display name; derived from given+surname when blank.
    display_name: str | None = Field(default=None, max_length=128)
    # AD account flags. ``None`` = aus der Zielgruppe übernehmen (ohne
    # Zielgruppe: bei erster Anmeldung ändern, sonst nichts).
    force_change: bool | None = None
    cannot_change_password: bool | None = None
    password_never_expires: bool | None = None
    # Per-student grade (-1 = 1. KG, 0 = 2. KG, 1..13). Ignored for teachers.
    jahrgangsstufe: int | None = Field(default=None, ge=-1, le=13)

    _ou = field_validator("ad_ou")(clean_ou)


class AdUserCreateResponse(BaseModel):
    ad_object_guid: str
    # Shown once so the operator can hand it out; never stored or returned again.
    temp_password: str
    force_change: bool = True


class AdUserDeleteResponse(BaseModel):
    ad_object_guid: str
    # True when the AD object was removed (False for a stale cache row).
    ad_removed: bool


class DemoPurgeResponse(BaseModel):
    found: bool
    schools: int = 0
    classes: int = 0
    users: int = 0


class AuditResetResponse(BaseModel):
    deleted: int = 0
    imports_deleted: int = 0


__all__ = [
    "AdUserCreateRequest",
    "AdUserCreateResponse",
    "AdUserDeleteResponse",
    "AuditResetResponse",
    "DemoPurgeResponse",
]
