"""Per-user preference schemas (self-service language / region / formats)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Language = Literal["de", "fr", "it", "en"]
DateFormat = Literal["DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"]
TimeFormat = Literal["24h", "12h"]


class UserPreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language: Language
    region: str
    date_format: DateFormat
    time_format: TimeFormat


class UserPreferencesUpdate(BaseModel):
    """Full replacement of the caller's preferences."""

    language: Language
    region: str
    date_format: DateFormat
    time_format: TimeFormat


__all__ = ["DateFormat", "Language", "TimeFormat", "UserPreferencesOut", "UserPreferencesUpdate"]
