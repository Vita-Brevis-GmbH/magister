"""Operator-editable document/mail templates (M6 Feature B, ADR-0009 D2).

A row overrides the built-in Jinja template for one ``(key, language, school)``.
``school_id`` NULL is the instance-wide default; a row scoped to a school wins
over the global one. When no active row matches, the renderer falls back to the
built-in template, so the out-of-the-box behaviour is unchanged.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow


class DocumentTemplate(Base):
    __tablename__ = "document_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Template key (e.g. "enrollment", "class_change", "password_handout").
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Locale ("de" | "fr" | "it" | "en").
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    # NULL = instance-wide default; a value scopes the override to one school.
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        # One row per (key, language, school). Postgres treats NULLs as distinct
        # in a plain unique index, so the global (school_id IS NULL) row needs a
        # separate partial unique index to stay singular.
        Index(
            "ix_document_templates_key_lang_school",
            "key",
            "language",
            "school_id",
            unique=True,
            postgresql_where=text("school_id IS NOT NULL"),
        ),
        Index(
            "ix_document_templates_key_lang_global",
            "key",
            "language",
            unique=True,
            postgresql_where=text("school_id IS NULL"),
        ),
    )
