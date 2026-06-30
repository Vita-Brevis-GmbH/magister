"""Per-user UI preferences (language, region, date/time formats).

Keyed by the authenticated user's objectGUID. Self-service; only staff
authenticate, so no student rows land here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

DEFAULT_LANGUAGE = "de"
DEFAULT_REGION = "CH"
DEFAULT_DATE_FORMAT = "DD.MM.YYYY"
DEFAULT_TIME_FORMAT = "24h"


class UserPreference(Base):
    __tablename__ = "user_preferences"

    ad_object_guid: Mapped[str] = mapped_column(String(36), primary_key=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default=DEFAULT_LANGUAGE)
    region: Mapped[str] = mapped_column(String(16), nullable=False, default=DEFAULT_REGION)
    date_format: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_DATE_FORMAT
    )
    time_format: Mapped[str] = mapped_column(String(8), nullable=False, default=DEFAULT_TIME_FORMAT)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
