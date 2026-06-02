from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base


class AdSyncState(Base):
    """Singleton row tracking AD incremental-sync cursor.

    There is at most one row, identified by ``id = 1``. The cursor
    ``last_when_changed`` is the maximum ``whenChanged`` value observed
    in the previous successful sync; subsequent incremental syncs filter
    AD for ``whenChanged >= last_when_changed`` and process only the
    delta.

    *Deletion-blindness:* AD's ``whenChanged`` does not surface
    tombstoned entries. A full sync (no cursor) must run periodically
    (default: weekly) to reconcile deletions. The scheduler enforces
    this via ``last_full_sync_at``.
    """

    __tablename__ = "ad_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_when_changed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_full_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_synced_count: Mapped[int] = mapped_column(Integer, default=0)
    last_mode: Mapped[str | None] = mapped_column(String(16), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
