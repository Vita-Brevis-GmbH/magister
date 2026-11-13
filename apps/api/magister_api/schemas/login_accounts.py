"""Schemas for the Keycloak login accounts (ADR-0025)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from magister_api.schemas.common import LoginName


class LoginAccountOut(BaseModel):
    id: int
    username: str
    display_name: str | None
    email: str | None
    #: Der Schlüssel für Rollen und Sitzungen — im Rolleneditor als
    #: ``ad_object_guid`` verwendet.
    principal_guid: str
    #: An ``issuer`` + ``subject`` gebunden, also schon einmal angemeldet.
    bound: bool
    enabled: bool
    #: Einer Person aus dem AD zugeordnet (``upn == username`` beim Anlegen).
    ad_linked: bool
    #: Steht in ``bootstrap_admins`` (Konsole): bekommt bei jeder Anmeldung
    #: die Admin-Rolle und lässt sich hier weder sperren noch löschen.
    bootstrap_admin: bool
    created_at: datetime
    last_login_at: datetime | None


class LoginAccountCreate(BaseModel):
    """Ein Konto vorab anlegen, damit Rollen vor der ersten Anmeldung passen."""

    username: LoginName
    display_name: str | None = Field(default=None, max_length=200)


class LoginAccountUpdate(BaseModel):
    enabled: bool


__all__ = ["LoginAccountCreate", "LoginAccountOut", "LoginAccountUpdate"]
