"""Local break-glass admin account.

A single row (``id=1``) stores the username + argon2id password hash for the
local-login path. Lockout state lives on the row so it survives a worker
restart. The actual session, once issued, is the same `Session` model the
OIDC flow uses — distinguished by ``auth_kind='local'`` and the sentinel
``ad_object_guid`` defined in ``services.local_admin``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class LocalAdmin(Base):
    __tablename__ = "local_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1 in M1.5
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, nullable=False
    )

    __table_args__ = (CheckConstraint("id = 1", name="local_admin_singleton"),)
