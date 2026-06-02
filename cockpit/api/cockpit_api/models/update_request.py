from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class UpdateRequestStatus(enum.StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class UpdateRequest(Base):
    __tablename__ = "update_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id", ondelete="CASCADE"), index=True
    )
    target_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[UpdateRequestStatus] = mapped_column(
        Enum(UpdateRequestStatus, name="update_request_status"),
        default=UpdateRequestStatus.pending,
    )
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    requested_by: Mapped[str | None] = mapped_column(String(200), default=None)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(String(1000), default=None)
