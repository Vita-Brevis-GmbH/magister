"""Auth-related models: AD user cache, sessions, role assignments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
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
    given_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    surname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mail: Mapped[str | None] = mapped_column(String(320), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ms_ds_consistency_guid: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

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
    """Admin and Schulleitung role grants.

    `role='admin'` always has ``school_id=NULL`` (cross-school).
    `role='schulleitung'` always has a non-null ``school_id``.
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
