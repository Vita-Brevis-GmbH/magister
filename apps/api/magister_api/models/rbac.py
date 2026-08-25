"""Dynamic role + role→capability matrix (M6 #3, ADR-0010).

The role→capability mapping is *data* here, not the code-fixed
``ROLE_CAPABILITIES`` table of ADR-0008. Capabilities themselves stay
code-defined (they are wired to endpoints); operators toggle which existing
capability a role holds and may add their own roles.

- ``Role`` — one row per role. ``is_admin`` marks the single super-role that
  holds every capability implicitly; ``is_system`` marks the seeded built-ins
  (not deletable); ``is_derived`` marks roles not stored in ``role_assignments``
  (``kl`` comes from ``class_teacher_roles``) — not assignable, not editable.
- ``RoleCapability`` — the editable matrix: one row per granted capability.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stable slug used in role_assignments.role and role_capabilities.role_key.
    key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class RoleCapability(Base):
    __tablename__ = "role_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("roles.key", ondelete="CASCADE"), nullable=False, index=True
    )
    # A Capability value (dotted identifier, e.g. "user.read"). Kept as a plain
    # string so an unknown/removed capability in the DB is simply ignored at load
    # time rather than breaking the schema.
    capability: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("role_key", "capability", name="uq_role_capabilities_role_cap"),
    )
