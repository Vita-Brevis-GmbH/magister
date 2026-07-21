"""Schools — first-class scope entity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class School(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kuerzel: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    scope_short: Mapped[str] = mapped_column(String(50), nullable=False)

    # Postal address + contact (all optional; filled in via the admin UI).
    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional map coordinates (WGS84). When set, the UI can render an
    # embedded map; the postal address always yields an "open in maps" link.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- AD provisioning config, PER SCHOOL ---
    # Target OUs and default group templates are per school so the right GPOs
    # and group settings apply to each Schulhaus. The student OU is chosen by
    # the class's Zyklus (Zyklus 3 vs the rest); teachers land in their own OU.
    # ``ad_ou_devices`` records the school's computer/device OU (for GPO scoping;
    # not yet a Magister write target). Unset OU = provisioning is refused with
    # a clear error rather than writing to a wrong OU. The Zyklus boundaries
    # themselves stay global (Lehrplan 21), only OU/group mapping is per school.
    ad_ou_students_zyklus3: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_ou_students_other: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_ou_teachers: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_ou_devices: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ad_groups_teacher: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_groups_student_zyklus1: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_groups_student_zyklus2: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ad_groups_student_zyklus3: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
