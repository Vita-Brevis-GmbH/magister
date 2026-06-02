"""Audit-Event model.

`payload` is stored encrypted-at-rest via PostgreSQL `pgcrypto` (column-level
``pgp_sym_encrypt``). It must only be read through the audit service, never via
direct ``SELECT payload FROM audit_events``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    actor_upn: Mapped[str | None] = mapped_column(String(320), nullable=True)
    actor_object_guid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Identifies the audit_key version that encrypted ``payload``.
    # Enables multi-key rotation: new writes carry the current key id,
    # old rows keep theirs so rotation can decrypt-then-re-encrypt one
    # batch at a time (hardening-audit M-03).
    key_id: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")

    __table_args__ = (Index("ix_audit_events_target", "target_kind", "target_id"),)
