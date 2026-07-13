"""Device model — inventory of school devices, managed in Magister.

Devices are imported from the AD Computer-OU by their *name* (the AD
``objectGUID`` is stored as the stable import identity), but every extra
attribute (Typ, Serien-/Inventarnummer, Notiz) and the *binding* to a
person, a class or a school lives here in Magister — never back in AD.

Assignment is one of four mutually exclusive states, enforced in the
service layer:

- assigned to a **person** — ``assigned_person_guid`` set (``school_id``
  is derived from that person's school);
- assigned to a **class** — ``class_id`` set (``school_id`` derived from
  the class);
- assigned to a **school** — ``school_id`` set, ``class_id`` and
  ``assigned_person_guid`` both NULL;
- **free / available** — all three NULL.

``school_id`` therefore doubles as the scope column for RBAC filtering.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

DEVICE_SOURCE_MANUAL = "manual"
DEVICE_SOURCE_AD = "ad"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scope + school-assignment. NULL = free pool (admin-visible; SMI sees it
    # as the assignable pool). Set (with class/person NULL) = assigned to school.
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="SET NULL"), nullable=True, index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Person-assignment mirrors the other tables: ad_object_guid string, no FK.
    assigned_person_guid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Stable identity for AD-imported devices (the Computer object's
    # objectGUID). NULL for manually created devices. Unique so the importer
    # can upsert idempotently.
    ad_object_guid: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=DEVICE_SOURCE_MANUAL)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
