"""Base repository with mandatory school-scope filter.

Per CLAUDE.md Niemals-Regel:
- Every personenbezogene-data query MUST be ``school_id``-filtered.
- Bypass requires an explicit ``# scope-bypass: <reason>`` code comment AND
  the ``bypass_scope=True`` keyword.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select


class ScopeError(RuntimeError):
    """Raised when a query is attempted without a usable school scope."""


@dataclass(frozen=True)
class ScopeContext:
    """Per-request scope info derived from the authenticated user."""

    ad_object_guid: str
    upn: str
    is_admin: bool = False
    school_scope: tuple[int, ...] = field(default_factory=tuple)
    roles: tuple[str, ...] = field(default_factory=tuple)

    def can_access_school(self, school_id: int | None) -> bool:
        if self.is_admin:
            return True
        if school_id is None:
            return False
        return school_id in self.school_scope


class BaseRepository:
    """Common helper machinery for school-scoped repositories.

    Subclasses receive a ``ScopeContext`` and must call :meth:`apply_scope`
    on every Select that touches a school-scoped table.
    """

    def __init__(self, session: AsyncSession, scope: ScopeContext | None = None) -> None:
        self.session = session
        self._scope = scope

    @property
    def scope(self) -> ScopeContext:
        if self._scope is None:
            raise ScopeError(
                "No ScopeContext on repository — refusing query. "
                "Use bypass_scope=True with a documented reason for admin-only flows."
            )
        return self._scope

    def apply_scope(
        self,
        stmt: Select[Any],
        school_id_column: Any,
        *,
        bypass_scope: bool = False,
    ) -> Select[Any]:
        """Apply WHERE school_id IN (scope) to the statement.

        - Admin users bypass automatically (full visibility).
        - ``bypass_scope=True`` requires a `# scope-bypass: <reason>` comment
          where the call site lives — enforced by code review, not at runtime.
        """
        if bypass_scope:
            return stmt
        if self._scope is None:
            raise ScopeError("apply_scope called without ScopeContext")
        if self._scope.is_admin:
            return stmt
        if not self._scope.school_scope:
            # Empty scope → no rows visible.
            return stmt.where(school_id_column.is_(None)).where(school_id_column.is_not(None))
        return stmt.where(school_id_column.in_(self._scope.school_scope))
