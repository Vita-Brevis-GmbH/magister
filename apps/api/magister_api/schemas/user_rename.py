"""Schemas for the guided name-change assistant (M6 Feature C, ADR-0009).

A rename (e.g. after marriage) cascades: a new surname drives a new
displayName, UPN, mail and sAMAccountName. ``preview`` proposes those values
from the new name; the operator edits and confirms them; ``apply`` writes them
in one audited operation and keeps the old primary address as an alias.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RenamePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_surname: str = Field(min_length=1, max_length=200)
    new_given_name: str | None = Field(default=None, max_length=200)


class RenamePreviewOut(BaseModel):
    """Suggested values — all editable by the operator before applying."""

    given_name: str | None
    surname: str
    display_name: str
    upn: str | None
    mail: str | None
    sam_account_name: str | None
    # The current primary address that ``apply`` would preserve as an alias.
    old_mail_kept_as_alias: str | None


class RenameApplyRequest(BaseModel):
    """The operator-confirmed final values. Only provided fields are written."""

    model_config = ConfigDict(extra="forbid")

    given_name: str | None = None
    surname: str | None = None
    display_name: str | None = None
    upn: str | None = None
    sam_account_name: str | None = None
    mail: str | None = None
    keep_old_mail_as_alias: bool = True


__all__ = [
    "RenameApplyRequest",
    "RenamePreviewOut",
    "RenamePreviewRequest",
]
