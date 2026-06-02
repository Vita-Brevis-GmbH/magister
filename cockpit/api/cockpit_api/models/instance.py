from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class InstanceChannel(enum.StrEnum):
    stable = "stable"
    latest = "latest"


class Instance(Base):
    __tablename__ = "instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(500))
    channel: Mapped[InstanceChannel] = mapped_column(
        Enum(InstanceChannel, name="instance_channel"), default=InstanceChannel.stable
    )
    deployed_version: Mapped[str | None] = mapped_column(String(64), default=None)
    latest_available_version: Mapped[str | None] = mapped_column(String(64), default=None)
    last_health_status: Mapped[str | None] = mapped_column(String(32), default=None)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(String(1000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
