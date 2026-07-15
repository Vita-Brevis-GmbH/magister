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
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    false,
    func,
    true,
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
    # Service-account bind mode: 'simple' (DN + password) or 'gssapi'
    # (Kerberos/keytab, no stored password). GUI-toggleable.
    ad_bind_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="simple", server_default="simple"
    )
    ad_bind_dn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_bind_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # LDAPS trust: optional pasted PEM CA bundle the DC cert is verified against
    # (public data, so plain Text — not encrypted like the bind password) and a
    # verify toggle. ``ad_tls_verify=False`` skips DC-cert validation entirely:
    # the transport stays encrypted (LDAPS 636) but is no longer authenticated.
    ad_tls_verify: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    ad_tls_ca_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Direct AD-credential login (username + password, LDAPS bind) as an
    # alternative to Entra/OIDC. ``ad_login_enabled`` is the master switch;
    # only members of ``ad_login_group`` (a DN or CN, direct membership) may
    # sign in that way. No MFA on this path.
    ad_login_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    ad_login_group: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_users_search_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Optional: subtree to walk for ``Computer`` objects whose ``managedBy``
    # points at a user. Unset = device sync is skipped silently.
    ad_computers_search_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default="15"
    )

    # Target OUs for provisioning new AD accounts via the student import.
    # The student OU is chosen by the class's Zyklus (Zyklus 3 vs the rest);
    # teachers land in their own OU. Unset = provisioning is refused with a
    # clear error (never fall back to a wrong OU).
    ad_ou_students_zyklus3: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_ou_students_other: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_ou_teachers: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Zyklus boundaries by Jahrgangsstufe: Zyklus 1 = grades ≤ z1_max, Zyklus 2
    # = z1_max+1..z2_max, Zyklus 3 = above z2_max. Defaults follow Lehrplan 21
    # (Z1: 1-2, Z2: 3-6, Z3: 7+). Drives the student provisioning target-OU.
    zyklus1_max_grade: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    zyklus2_max_grade: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6, server_default="6"
    )

    # Master switch for the per-user password vault. When off, stored passwords
    # are ignored (never read/written) regardless of the per-user flag.
    password_store_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Default AD groups assigned to newly provisioned accounts, per category
    # (teacher / student by Zyklus). Each a JSON list of group DNs. Empty = none.
    ad_groups_teacher: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_groups_student_zyklus1: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_groups_student_zyklus2: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_groups_student_zyklus3: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # --- Audit fingerprint ---
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_upn: Mapped[str | None] = mapped_column(String(320), nullable=True)

    __table_args__ = (CheckConstraint("id = 1", name="app_settings_singleton"),)
