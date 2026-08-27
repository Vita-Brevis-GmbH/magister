"""AD group templates ("Zielrollen"): named, reusable bundles of AD groups.

A group template is a set of AD group DNs that grant access to tools or data.
It is chosen at "neuen Benutzer anlegen" (filtered by the target Standort); the
new account is added to the template's AD groups. This is the editable,
self-serviceable successor to the per-school ``ad_groups_*`` columns (which stay
as a provisioning fallback when no template is picked).

Templates are AD-global config (not personenbezogen), assignable to one or more
Standorte via :class:`GroupTemplateSchool`. A template with *no* Standort links
is "global" — offered at every Standort.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from magister_api.models.base import Base, utcnow

GROUP_TEMPLATE_STATUS_ACTIVE = "active"
GROUP_TEMPLATE_STATUS_ARCHIVED = "archived"
ALLOWED_STATUSES: frozenset[str] = frozenset(
    {GROUP_TEMPLATE_STATUS_ACTIVE, GROUP_TEMPLATE_STATUS_ARCHIVED}
)


class GroupTemplate(Base):
    __tablename__ = "group_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance / defaulting hint (teacher | student_zyklus1..3 | company |
    # custom). Free-form; not constrained.
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ad_groups: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GROUP_TEMPLATE_STATUS_ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{GROUP_TEMPLATE_STATUS_ACTIVE}', '{GROUP_TEMPLATE_STATUS_ARCHIVED}')",
            name="ck_group_templates_status",
        ),
    )


class GroupTemplateSchool(Base):
    """M2M link: a template is offered at these Standorte (none = global)."""

    __tablename__ = "group_template_schools"

    group_template_id: Mapped[int] = mapped_column(
        ForeignKey("group_templates.id", ondelete="CASCADE"), primary_key=True
    )
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), primary_key=True, index=True
    )
