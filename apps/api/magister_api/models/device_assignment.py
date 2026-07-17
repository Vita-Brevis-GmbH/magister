"""Device assignment history — one row per assignment period.

Every time a device is (re)assigned or freed, the currently-open row is closed
(``valid_to`` set) and — when the device lands on a new holder — a new open row
is inserted. This gives a full "who had this device, when, and was it a loaner"
trail that survives the holder being deleted (the display ``label`` is snapshot
at assignment time, so it stays readable even after the user is gone).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # person / class / school — mirrors the device assignment target.
    assignment_type: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_person_guid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), nullable=True
    )
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of the holder's display name at assignment time, so the history
    # stays readable even after the person/class is deleted.
    label: Mapped[str] = mapped_column(String(320), nullable=False)
    is_loan: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
