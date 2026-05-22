"""Singleton ``app_settings`` row that holds OIDC + AD configuration.

The plaintext-secret columns (``oidc_client_secret``, ``ad_bind_password``) are
stored as encrypted bytes (``LargeBinary``) using the same pgcrypto pattern
that ``audit_events.payload`` uses (``pgp_sym_encrypt`` with
``MAGISTER_AUDIT_KEY``). ``version`` is bumped on every write and used by the
OIDC/AD client cache to invalidate without a process restart.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # --- OIDC ---
    oidc_issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_client_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    oidc_redirect_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    oidc_scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    bootstrap_admins: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Allowlist of mail domains the user-edit form may pick from for UPN
    # and mail attributes (e.g. ["schule.example.ch", "lehrer.example.ch"]).
    # An empty list means no domains are configured — the user-PATCH
    # endpoint then refuses any UPN/mail change. Schulträger-IT pflegt
    # diese Liste im Admin-GUI.
    mail_domains: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # --- AD ---
    ad_dcs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_bind_dn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_bind_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ad_users_search_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default="15"
    )

    # --- Audit fingerprint ---
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_upn: Mapped[str | None] = mapped_column(String(320), nullable=True)

    __table_args__ = (CheckConstraint("id = 1", name="app_settings_singleton"),)
