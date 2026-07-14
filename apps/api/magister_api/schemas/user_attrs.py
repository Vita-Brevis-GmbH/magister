"""Schemas for ``PATCH /users/{ad_object_guid}`` — editable user attributes.

Each field is optional: omitted = leave alone.

- ``upn`` and ``sam_account_name`` must be non-empty when present (login-relevant).
- ``mail`` and the address fields may be sent as empty string or ``null`` to clear.
- ``temp_device_name`` is Magister-only — never written to AD.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# pre-Win2000 logon name: per Microsoft, ≤20 chars, no special chars other
# than `._-`. AD itself allows broader sets but Magister keeps a strict
# subset that matches what schools typically configure.
SAM_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9._-]{1,20}$")

# Local-part of an email address — RFC-2822 simplified, no quotes/specials.
UPN_LOCAL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}$")


class UserAttributesUpdate(BaseModel):
    """Patch payload for the user attributes endpoint.

    Domain-allowlist checks for ``upn`` / ``mail`` happen in the service
    against the configured ``mail_domains`` — the Pydantic layer only
    enforces shape.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=200)
    given_name: str | None = Field(default=None, max_length=200)
    surname: str | None = Field(default=None, max_length=200)
    upn: str | None = Field(default=None, max_length=320)
    sam_account_name: str | None = Field(default=None, max_length=20)
    mail: str | None = Field(default=None, max_length=320)
    street_address: str | None = Field(default=None, max_length=200)
    locality: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=16)
    country: str | None = Field(default=None, max_length=100)
    temp_device_name: str | None = Field(default=None, max_length=100)
    # Magister-only per-student grade (-1..13); null clears it.
    jahrgangsstufe: int | None = Field(default=None, ge=-1, le=13)
    # AD account-policy flags (omitted = leave alone).
    password_never_expires: bool | None = Field(default=None)
    cannot_change_password: bool | None = Field(default=None)
    # Password vault opt-in (Magister-only). Turning it off clears any stored PW.
    store_password: bool | None = Field(default=None)

    @field_validator("upn")
    @classmethod
    def _check_upn(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # UPN must be non-empty (login-relevant; clearing it would brick the user).
        if not v.strip():
            raise ValueError("upn_required")
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("upn_invalid_format")
        local, _, domain = v.partition("@")
        if not UPN_LOCAL_RE.match(local) or not domain:
            raise ValueError("upn_invalid_format")
        return v

    @field_validator("sam_account_name")
    @classmethod
    def _check_sam(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("sam_account_name_required")
        v = v.strip()
        if not SAM_ACCOUNT_RE.match(v):
            raise ValueError("sam_account_name_invalid")
        return v

    @field_validator("mail")
    @classmethod
    def _check_mail(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("mail_invalid_format")
        local, _, domain = v.partition("@")
        if not UPN_LOCAL_RE.match(local) or not domain:
            raise ValueError("mail_invalid_format")
        return v


__all__ = ["UserAttributesUpdate", "SAM_ACCOUNT_RE", "UPN_LOCAL_RE"]
