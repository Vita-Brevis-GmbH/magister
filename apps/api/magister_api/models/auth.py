"""Auth-related models: AD user cache, sessions, role assignments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class AdUserCache(Base):
    """Snapshot of AD users (teachers/students/admins). Filled by the periodic AD sync.

    Bootstrap admins are upserted on first login even before any sync ran.
    """

    __tablename__ = "ad_user_cache"

    ad_object_guid: Mapped[str] = mapped_column(String(36), primary_key=True)
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    upn: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    sam_account_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    given_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    surname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mail: Mapped[str | None] = mapped_column(String(320), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ms_ds_consistency_guid: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Physical-address attributes mirrored from AD (streetAddress, l,
    # postalCode, co). Free-text so we can mirror what AD has without
    # imposing a structure the school's IT may not maintain.
    street_address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Device-Zuordnung. ``device_name`` mirrors the primary device synced
    # from AD's Computer-OU (``managedBy=<user-dn>``) — populated by the
    # Phase-4 device sync; settable manually as fallback.
    # ``temp_device_name`` is Magister-only: a loan device while the
    # primary is in repair. Never written to AD.
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Per-student grade level (Magister-only, not an AD attribute): -1 = 1. KG,
    # 0 = 2. KG, 1..13 = Klassen. NULL for teachers/admins or unset students.
    # Preserved across AD syncs (omitted from the sync upsert) and bumped during
    # class promotion.
    jahrgangsstufe: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # AD account-policy flags. ``password_never_expires`` mirrors the
    # userAccountControl DONT_EXPIRE_PASSWD bit (round-tripped by the sync).
    # ``cannot_change_password`` is Magister-tracked intent: it is enforced in
    # AD via the object's DACL (deny Change-Password), which the sync does not
    # read back — so it is preserved across syncs like ``jahrgangsstufe``.
    password_never_expires: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    cannot_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Password vault (opt-in per user; global toggle in app_settings). When on,
    # Magister keeps the last set password, encrypted at rest via pgcrypto
    # (``password_enc``) with the app-secrets key — never stored in plaintext.
    store_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    password_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    __table_args__ = (Index("ix_ad_user_cache_kind_enabled", "kind", "enabled"),)


class Session(Base):
    """Server-side session record. Cookie carries only the opaque session id.

    Sessions can be issued by either the OIDC flow (``auth_kind='oidc'``,
    ``oidc_subject`` set) or by the local-admin login (``auth_kind='local'``,
    ``oidc_subject=''``). The ``ad_object_guid`` is always populated — local
    admin sessions point at a stable sentinel guid.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ad_object_guid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    oidc_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="oidc", default="oidc"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RoleAssignment(Base):
    """Admin, Schulleitung and SMI role grants.

    `role='admin'` always has ``school_id=NULL`` (cross-school).
    `role='schulleitung'` always has a non-null ``school_id`` (one row per school).
    `role='smi'` always has a non-null ``school_id`` (one row per school;
    grant on every school of the Schulträger to give cross-school reach).
    """

    __tablename__ = "role_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_object_guid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ad_object_guid",
            "role",
            "school_id",
            name="uq_role_assignments_user_role_school",
        ),
    )
