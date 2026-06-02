from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class ServiceToken(Base):
    """Rotatable bearer token for cockpit access.

    Hardening-audit M-01: replaces the single static ``bootstrap_token``
    in production. The bootstrap token stays as a break-glass admin
    credential, but every operational caller (UI, runner, ansible) gets
    its own token with a finite ``expires_at``.

    Only ``token_hash`` (sha256) is stored — never the raw token.
    """

    __tablename__ = "service_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
