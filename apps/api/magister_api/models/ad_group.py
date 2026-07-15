"""Catalog of AD security/distribution groups, synced from the directory.

Populated by the full AD sync (:mod:`magister_api.services.ad_sync`) so the
GUI can offer group DNs as pickable checkboxes for the provisioning templates
(Userkonfiguration) instead of forcing the operator to type raw DNs.

Groups are AD-global (not personal data), so the catalog carries no
``school_id`` scope — it is a read-only convenience mirror keyed by the group's
``objectGUID``. The authoritative membership assignment still writes to the AD
group's ``member`` attribute; this table only lists what groups exist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base


class AdGroupCache(Base):
    __tablename__ = "ad_group_cache"

    ad_object_guid: Mapped[str] = mapped_column(String(36), primary_key=True)
    distinguished_name: Mapped[str] = mapped_column(String(512), nullable=False)
    cn: Mapped[str] = mapped_column(String(256), nullable=False)
    sam_account_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["AdGroupCache"]
