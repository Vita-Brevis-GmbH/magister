"""Schemas for the GUI-editable app settings.

Two surfaces:
- ``AppSettingsOut`` — for the GUI; never carries plaintext secrets,
  only ``oidc_client_secret_set: bool`` / ``ad_bind_password_set: bool``.
- ``AppSettingsUpdate`` — accepted by ``PUT /admin/app-settings``; secrets
  are optional plain strings, and an empty/missing value means "leave the
  stored secret untouched".
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    ad_bind_mode: str
    ad_bind_dn: str | None
    ad_bind_password_set: bool
    ad_tls_verify: bool
    # Public CA certificate (PEM) — safe to return so the GUI can display /
    # edit it. None when no CA has been imported.
    ad_tls_ca_pem: str | None
    ad_users_search_base: str | None
    ad_computers_search_base: str | None
    ad_sync_interval_minutes: int

    # Provisioning target OUs (student import).
    ad_ou_students_zyklus3: str | None
    ad_ou_students_other: str | None
    ad_ou_teachers: str | None

    # Zyklus boundaries by Jahrgangsstufe.
    zyklus1_max_grade: int
    zyklus2_max_grade: int

    # Password vault master switch.
    password_store_enabled: bool

    # Optional subtree walked for the group catalog (global).
    ad_groups_search_base: str | None

    # Default AD groups per provisioning category (lists of group DNs).
    ad_groups_teacher: list[str]
    ad_groups_student_zyklus1: list[str]
    ad_groups_student_zyklus2: list[str]
    ad_groups_student_zyklus3: list[str]

    # Whether a custom webserver TLS cert is imported (else self-signed). The
    # cert/key bodies are never returned — only this presence flag.
    web_tls_cert_set: bool = False

    # NinjaOne connector (ADR-0012). The client secret is never returned — only
    # the presence flag, like the OIDC/AD secrets.
    ninja_enabled: bool = False
    ninja_region: str | None = None
    ninja_client_id: str | None = None
    ninja_client_secret_set: bool = False

    # Mailversand + Ablauf-Erinnerung. Das Geheimnis (SMTP-Passwort bzw.
    # Graph-Client-Secret) kommt nie zurück — nur ob eines hinterlegt ist.
    mail_transport: str = "off"
    mail_from: str | None = None
    mail_from_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str = "starttls"
    smtp_username: str | None = None
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    mail_secret_set: bool = False
    expiry_notice_enabled: bool = False
    expiry_notice_days: list[int] = Field(default_factory=lambda: [14, 7, 1])

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
    ad_bind_mode: str | None = None
    ad_bind_dn: str | None = None
    ad_bind_password: str | None = Field(
        default=None,
        description=(
            "Send a non-empty string to update; omit or send null to leave the "
            "current encrypted value untouched."
        ),
    )
    ad_tls_verify: bool | None = None
    ad_tls_ca_pem: str | None = Field(
        default=None,
        description=(
            "Inline PEM CA bundle the DC cert is verified against. Send null / "
            "omit to leave unchanged; send an empty string to clear (fall back "
            "to the OS trust store)."
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

    # Zyklus boundaries (grade 1..13). z1_max < z2_max.
    zyklus1_max_grade: int | None = Field(default=None, ge=1, le=13)
    zyklus2_max_grade: int | None = Field(default=None, ge=1, le=13)

    password_store_enabled: bool | None = Field(default=None)

    # Optional subtree to walk for the group catalog. Empty string clears.
    ad_groups_search_base: str | None = None

    ad_groups_teacher: list[str] | None = Field(default=None)
    ad_groups_student_zyklus1: list[str] | None = Field(default=None)
    ad_groups_student_zyklus2: list[str] | None = Field(default=None)
    ad_groups_student_zyklus3: list[str] | None = Field(default=None)

    # --- Webserver TLS certificate import ---
    # Provide a PEM cert chain + private key together, OR a base64 PFX (+ its
    # password). Send both PEM fields as empty strings to clear (revert to the
    # self-signed fallback). Null/omit on all → leave the stored cert unchanged.
    web_tls_cert_pem: str | None = Field(
        default=None,
        description="PEM certificate chain (leaf first). Pair with web_tls_key_pem.",
    )
    web_tls_key_pem: str | None = Field(
        default=None,
        description="PEM private key matching the leaf certificate. Never returned.",
    )
    web_tls_pfx_base64: str | None = Field(
        default=None,
        description="Base64-encoded PKCS#12/PFX blob (alternative to the PEM pair).",
    )
    web_tls_pfx_password: str | None = Field(
        default=None,
        description="Password for the PFX blob, if any.",
    )

    # --- NinjaOne connector (ADR-0012) ---
    ninja_enabled: bool | None = None
    ninja_region: str | None = Field(
        default=None,
        description="NinjaOne cloud instance: us / us2 / eu / ca / oc. Empty string clears.",
    )
    ninja_client_id: str | None = None
    ninja_client_secret: str | None = Field(
        default=None,
        description=(
            "Send a non-empty string to update; omit or send null to leave the "
            "current encrypted value untouched."
        ),
    )

    # --- Mailversand (Ablauf-Erinnerungen) ---
    mail_transport: str | None = Field(default=None, description="off / smtp / graph")
    mail_from: str | None = Field(default=None, max_length=320)
    mail_from_name: str | None = Field(default=None, max_length=128)
    smtp_host: str | None = Field(default=None, max_length=255)
    # 0 leert das Feld (Vorgabe 587 bzw. 465 je nach smtp_security).
    smtp_port: int | None = Field(default=None, ge=0, le=65535)
    smtp_security: str | None = Field(default=None, description="starttls / tls")
    smtp_username: str | None = Field(default=None, max_length=320)
    graph_tenant_id: str | None = Field(default=None, max_length=64)
    graph_client_id: str | None = Field(default=None, max_length=64)
    mail_secret: str | None = Field(
        default=None,
        description=(
            "SMTP-Passwort bzw. Graph-Client-Secret. Nicht leer = neu setzen; "
            "null/weglassen = unverändert."
        ),
    )
    clear_mail_secret: bool | None = Field(
        default=None, description="true entfernt das hinterlegte Geheimnis."
    )
    expiry_notice_enabled: bool | None = None
    expiry_notice_days: list[int] | None = Field(
        default=None, description="Tage vor dem Ablauf, an denen erinnert wird (1–90)."
    )

    @field_validator("mail_transport")
    @classmethod
    def _check_mail_transport(cls, v: str | None) -> str | None:
        if v is not None and v.strip() and v not in {"off", "smtp", "graph"}:
            raise ValueError("mail_transport must be off, smtp or graph")
        return v

    @field_validator("smtp_security")
    @classmethod
    def _check_smtp_security(cls, v: str | None) -> str | None:
        # Unverschlüsselt gibt es nicht: STARTTLS (587) oder TLS (465).
        if v is not None and v.strip() and v not in {"starttls", "tls"}:
            raise ValueError("smtp_security must be starttls or tls")
        return v

    @field_validator("mail_from")
    @classmethod
    def _check_mail_from(cls, v: str | None) -> str | None:
        if v is not None and v.strip() and not _MAIL_RE.match(v.strip()):
            raise ValueError("mail_from must be an e-mail address")
        return v

    @field_validator("expiry_notice_days")
    @classmethod
    def _check_days(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if not 1 <= len(v) <= 5 or any(not 1 <= d <= 90 for d in v):
            raise ValueError("expiry_notice_days: 1 to 5 values between 1 and 90")
        return sorted(set(v), reverse=True)

    @field_validator("ninja_region")
    @classmethod
    def _check_ninja_region(cls, v: str | None) -> str | None:
        if v is not None and v.strip() and v not in {"us", "us2", "eu", "ca", "oc"}:
            raise ValueError("ninja_region must be one of us/us2/eu/ca/oc")
        return v

    @field_validator("ad_bind_mode")
    @classmethod
    def _check_bind_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in {"simple", "gssapi"}:
            raise ValueError("ad_bind_mode must be 'simple' or 'gssapi'")
        return v

    @field_validator("ad_tls_ca_pem")
    @classmethod
    def _check_ca_pem(cls, v: str | None) -> str | None:
        # Empty string is the explicit "clear" sentinel; anything else must at
        # least look like a PEM certificate so we fail fast with a clean 422
        # instead of only surfacing the problem at connect time.
        if v is not None and v.strip() and "-----BEGIN CERTIFICATE-----" not in v:
            raise ValueError("ad_tls_ca_pem must be a PEM certificate")
        return v

    @model_validator(mode="after")
    def _check_zyklus_order(self) -> AppSettingsUpdate:
        if (
            self.zyklus1_max_grade is not None
            and self.zyklus2_max_grade is not None
            and self.zyklus1_max_grade >= self.zyklus2_max_grade
        ):
            raise ValueError("zyklus1_max_grade must be < zyklus2_max_grade")
        return self


_MAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

__all__ = ["AppSettingsOut", "AppSettingsUpdate"]
