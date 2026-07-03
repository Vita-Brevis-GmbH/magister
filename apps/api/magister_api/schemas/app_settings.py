"""Schemas for the GUI-editable app settings.

Two surfaces:
- ``AppSettingsOut`` — for the GUI; never carries plaintext secrets,
  only ``oidc_client_secret_set: bool`` / ``ad_bind_password_set: bool``.
- ``AppSettingsUpdate`` — accepted by ``PUT /admin/app-settings``; secrets
  are optional plain strings, and an empty/missing value means "leave the
  stored secret untouched".
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AppSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int

    # OIDC
    oidc_issuer: str | None
    oidc_client_id: str | None
    oidc_client_secret_set: bool
    oidc_redirect_uri: str | None
    oidc_scopes: list[str]
    bootstrap_admins: list[str]
    mail_domains: list[str]

    # AD
    ad_dcs: list[str]
    ad_bind_dn: str | None
    ad_bind_password_set: bool
    ad_users_search_base: str | None
    ad_computers_search_base: str | None
    ad_sync_interval_minutes: int

    # Provisioning target OUs (student import).
    ad_ou_students_zyklus3: str | None
    ad_ou_students_other: str | None
    ad_ou_teachers: str | None

    # Audit fingerprint
    updated_at: datetime
    updated_by_upn: str | None


class AppSettingsUpdate(BaseModel):
    """Each field is optional. Strings empty by client convention mean "clear",
    but for the two ``*_secret``/``*_password`` fields a missing or empty value
    means "leave the stored secret untouched". To clear a secret, send the
    sentinel ``""`` AND set its sibling field (e.g. clearing oidc_client_secret
    only makes sense if you also clear oidc_client_id).
    """

    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = Field(
        default=None,
        description=(
            "Send a non-empty string to update; omit or send null to leave the "
            "current encrypted value untouched."
        ),
    )
    oidc_redirect_uri: str | None = None
    oidc_scopes: list[str] | None = None
    bootstrap_admins: list[str] | None = None
    mail_domains: list[str] | None = Field(
        default=None,
        description=(
            "Allowlist of mail/UPN domains the user-edit form may pick from. "
            "Send an empty list to clear; send null/omit to leave unchanged."
        ),
    )

    ad_dcs: list[str] | None = None
    ad_bind_dn: str | None = None
    ad_bind_password: str | None = Field(
        default=None,
        description=(
            "Send a non-empty string to update; omit or send null to leave the "
            "current encrypted value untouched."
        ),
    )
    ad_users_search_base: str | None = None
    ad_computers_search_base: str | None = None
    ad_sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)

    # Provisioning target OUs. Send an empty string to clear (disables
    # provisioning for that bucket); send null/omit to leave unchanged.
    ad_ou_students_zyklus3: str | None = None
    ad_ou_students_other: str | None = None
    ad_ou_teachers: str | None = None


__all__ = ["AppSettingsOut", "AppSettingsUpdate"]
