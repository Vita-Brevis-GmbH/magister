"""BaseRepository.apply_scope behaviour — pure SQL-construction unit tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from magister_api.models.audit import AuditEvent
from magister_api.repositories.base import BaseRepository, ScopeContext, ScopeError


def _compile(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]


class TestApplyScope:
    def test_admin_no_filter(self) -> None:
        ctx = ScopeContext(ad_object_guid="g", upn="a@x.ch", is_admin=True)
        repo = BaseRepository(session=None, scope=ctx)  # type: ignore[arg-type]
        stmt = select(AuditEvent.id)
        out = repo.apply_scope(stmt, AuditEvent.school_id)
        assert "school_id" not in _compile(out).lower()

    def test_schulleitung_in_clause(self) -> None:
        ctx = ScopeContext(ad_object_guid="g", upn="a@x.ch", is_admin=False, school_scope=(1, 7))
        repo = BaseRepository(session=None, scope=ctx)  # type: ignore[arg-type]
        stmt = select(AuditEvent.id)
        out = _compile(repo.apply_scope(stmt, AuditEvent.school_id))
        assert "audit_events.school_id IN (1, 7)" in out

    def test_empty_scope_returns_no_rows(self) -> None:
        ctx = ScopeContext(ad_object_guid="g", upn="a@x.ch", is_admin=False, school_scope=())
        repo = BaseRepository(session=None, scope=ctx)  # type: ignore[arg-type]
        stmt = select(AuditEvent.id)
        out = _compile(repo.apply_scope(stmt, AuditEvent.school_id))
        assert "IS NULL" in out
        assert "IS NOT NULL" in out

    def test_no_scope_raises(self) -> None:
        repo = BaseRepository(session=None, scope=None)  # type: ignore[arg-type]
        stmt = select(AuditEvent.id)
        with pytest.raises(ScopeError):
            repo.apply_scope(stmt, AuditEvent.school_id)

    def test_explicit_bypass_skips_filter(self) -> None:
        repo = BaseRepository(session=None, scope=None)  # type: ignore[arg-type]
        stmt = select(AuditEvent.id)
        # scope-bypass: unit-test verifying bypass semantics
        out = _compile(repo.apply_scope(stmt, AuditEvent.school_id, bypass_scope=True))
        # Bypass means no WHERE clause was added.
        assert " WHERE " not in out.upper()

    def test_can_access_school_admin(self) -> None:
        ctx = ScopeContext(ad_object_guid="g", upn="a@x.ch", is_admin=True)
        assert ctx.can_access_school(99) is True
        assert ctx.can_access_school(None) is True

    def test_can_access_school_schulleitung(self) -> None:
        ctx = ScopeContext(ad_object_guid="g", upn="a@x.ch", school_scope=(1, 2))
        assert ctx.can_access_school(1) is True
        assert ctx.can_access_school(2) is True
        assert ctx.can_access_school(3) is False
        assert ctx.can_access_school(None) is False
