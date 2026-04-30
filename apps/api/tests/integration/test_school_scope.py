"""Repository school-scope filter against a real DB.

DoD for issue #1: school_id-Filter im Repository-Base-Class durchgesetzt + getestet.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.school import School
from magister_api.repositories.base import BaseRepository, ScopeContext

pytestmark = pytest.mark.postgres


def _settings() -> Settings:
    return Settings(
        audit_key="scope-test-key",  # type: ignore[arg-type]
        session_secret="x",  # type: ignore[arg-type]
        csrf_secret="x",  # type: ignore[arg-type]
    )


@pytest.fixture
async def two_schools(db_session: AsyncSession) -> tuple[int, int]:
    a = School(name="Schule A", kuerzel="A", scope_short="A")
    b = School(name="Schule B", kuerzel="B", scope_short="B")
    db_session.add_all([a, b])
    await db_session.flush()
    return a.id, b.id


class TestSchoolScopeFilter:
    @pytest.mark.asyncio
    async def test_user_only_sees_their_schools(
        self, db_session: AsyncSession, two_schools: tuple[int, int]
    ) -> None:
        sa, sb = two_schools
        svc = AuditService(db_session, _settings())
        await svc.emit(
            action="class_created",
            target_kind="class",
            target_id="1",
            actor_upn="x@x.ch",
            actor_object_guid=None,
            school_id=sa,
            ip=None,
            request_id="r-a",
            payload={"school": "A"},
        )
        await svc.emit(
            action="class_created",
            target_kind="class",
            target_id="2",
            actor_upn="x@x.ch",
            actor_object_guid=None,
            school_id=sb,
            ip=None,
            request_id="r-b",
            payload={"school": "B"},
        )
        await db_session.flush()

        # User scoped to school A only sees school-A events.
        ctx = ScopeContext(ad_object_guid="g", upn="kl@x.ch", is_admin=False, school_scope=(sa,))
        repo = BaseRepository(db_session, ctx)
        stmt = repo.apply_scope(select(AuditEvent.school_id), AuditEvent.school_id)
        rows = (await db_session.execute(stmt)).scalars().all()
        assert set(rows) == {sa}

    @pytest.mark.asyncio
    async def test_admin_sees_everything(
        self, db_session: AsyncSession, two_schools: tuple[int, int]
    ) -> None:
        sa, sb = two_schools
        svc = AuditService(db_session, _settings())
        await svc.emit(
            action="x",
            target_kind="class",
            target_id="1",
            actor_upn="x@x.ch",
            actor_object_guid=None,
            school_id=sa,
            ip=None,
            request_id="r",
            payload={},
        )
        await svc.emit(
            action="x",
            target_kind="class",
            target_id="2",
            actor_upn="x@x.ch",
            actor_object_guid=None,
            school_id=sb,
            ip=None,
            request_id="r",
            payload={},
        )
        await db_session.flush()
        ctx = ScopeContext(ad_object_guid="g", upn="adm@x.ch", is_admin=True)
        repo = BaseRepository(db_session, ctx)
        stmt = repo.apply_scope(select(AuditEvent.school_id), AuditEvent.school_id)
        rows = (await db_session.execute(stmt)).scalars().all()
        assert set(rows) == {sa, sb}

    @pytest.mark.asyncio
    async def test_empty_scope_sees_nothing(
        self, db_session: AsyncSession, two_schools: tuple[int, int]
    ) -> None:
        sa, _sb = two_schools
        svc = AuditService(db_session, _settings())
        await svc.emit(
            action="x",
            target_kind="class",
            target_id="1",
            actor_upn="x@x.ch",
            actor_object_guid=None,
            school_id=sa,
            ip=None,
            request_id="r",
            payload={},
        )
        await db_session.flush()
        ctx = ScopeContext(ad_object_guid="g", upn="nobody@x.ch", is_admin=False, school_scope=())
        repo = BaseRepository(db_session, ctx)
        stmt = repo.apply_scope(select(AuditEvent.school_id), AuditEvent.school_id)
        rows = (await db_session.execute(stmt)).scalars().all()
        assert rows == []
