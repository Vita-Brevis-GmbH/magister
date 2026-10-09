"""Der Abgleich gegen eine echte Datenbank (ADR-0017 D3/D4).

Die eine Zusage, die sich nur hier prüfen lässt: **ein zweiter Lauf schreibt
nichts.** Er erhöht die Versionsnummer nicht und schreibt kein
Audit-Ereignis. Das ist der Unterschied zwischen einem Abgleich und einer
Schleife, die alle fünf Minuten dasselbe in die Datenbank schiebt — und der
Grund, weshalb der Reconciler nicht einfach `AppSettingsService.update()`
aufruft.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.services.reconciler import RECONCILER_ACTOR, Reconciler
from magister_api.tenancy.desired_state import DesiredState

pytestmark = pytest.mark.postgres


async def _version(session: AsyncSession) -> int:
    return (
        await session.execute(select(AppSettings.version).where(AppSettings.id == 1))
    ).scalar_one()


async def _reconcile_events(session: AsyncSession) -> int:
    stmt = (
        select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_upn == RECONCILER_ACTOR)
    )
    return (await session.execute(stmt)).scalar_one()


class TestOnlyTheDifferenceIsWritten:
    async def test_a_change_is_applied_once_and_audited(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        before_version = await _version(db_session)
        desired = DesiredState(settings={"ad_sync_interval_minutes": 17})

        result = await Reconciler(db_session, app_settings).reconcile(desired, tenant_slug="alpha")
        await db_session.commit()

        assert result.changed_settings == {
            "ad_sync_interval_minutes": (
                result.changed_settings["ad_sync_interval_minutes"][0],
                17,
            )
        }
        applied = (
            await db_session.execute(
                select(AppSettings.ad_sync_interval_minutes).where(AppSettings.id == 1)
            )
        ).scalar_one()
        assert applied == 17
        assert await _version(db_session) == before_version + 1
        assert await _reconcile_events(db_session) == 1

    async def test_the_second_run_writes_nothing(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Die Zusage aus D4, und der Grund für den ganzen Vergleich."""
        desired = DesiredState(settings={"ad_sync_interval_minutes": 23})
        svc = Reconciler(db_session, app_settings)

        first = await svc.reconcile(desired, tenant_slug="alpha")
        await db_session.commit()
        assert first.touched

        version_after_first = await _version(db_session)
        events_after_first = await _reconcile_events(db_session)

        second = await svc.reconcile(desired, tenant_slug="alpha")
        await db_session.commit()

        assert not second.touched
        assert second.changed_settings == {}
        assert await _version(db_session) == version_after_first
        assert await _reconcile_events(db_session) == events_after_first

    async def test_a_reordered_list_does_not_count_as_a_change(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        svc = Reconciler(db_session, app_settings)
        await svc.reconcile(
            DesiredState(settings={"mail_domains": ["a.ch", "b.ch"]}), tenant_slug="alpha"
        )
        await db_session.commit()
        version = await _version(db_session)

        result = await svc.reconcile(
            DesiredState(settings={"mail_domains": ["b.ch", "a.ch"]}), tenant_slug="alpha"
        )
        await db_session.commit()

        assert not result.touched
        assert await _version(db_session) == version

    async def test_an_unknown_key_is_dropped_not_written(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Eine neuere Konsole darf den Rest nicht blockieren — und nichts Fremdes schreiben."""
        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(settings={"ad_sync_interval_minutes": 31, "erfundenes_feld": "wert"}),
            tenant_slug="alpha",
        )
        await db_session.commit()

        assert result.unknown_keys == ["erfundenes_feld"]
        assert "ad_sync_interval_minutes" in result.changed_settings


class TestRbacReconcile:
    async def test_only_the_named_roles_are_touched(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Eine Vorgabe ist eine Aussage über die genannten Rollen.

        Sonst löschte eine Vorgabe mit zwei Rollen die eigenen Rollen des
        Kunden mit — und niemand hätte das gemeint.
        """
        from magister_api.services.rbac import RbacService

        rbac = RbacService(db_session)
        before = await rbac.capabilities_by_role()
        untouched_role = next((key for key in before if key not in {"admin", "kl"}), None)
        if untouched_role is None:
            pytest.skip("Keine zweite Rolle mit Rechten in dieser Installation")
        before_caps = sorted(before[untouched_role])

        await Reconciler(db_session, app_settings).reconcile(
            DesiredState(rbac={"lehrperson": ["user.read"]}), tenant_slug="alpha"
        )
        await db_session.commit()

        after = await RbacService(db_session).capabilities_by_role()
        assert sorted(after.get(untouched_role, [])) == before_caps

    async def test_an_unknown_role_is_skipped_with_a_reason(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Eine Rolle, die es beim Kunden nicht gibt, wird nicht angelegt.

        Rollen anzulegen ist eine Aussage über die Organisation des Kunden;
        eine Rechte-Vorgabe ist es nicht.
        """
        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(rbac={"gibt_es_nicht": ["user.read"]}), tenant_slug="alpha"
        )
        await db_session.commit()

        assert "gibt_es_nicht" in result.skipped_roles
        assert result.changed_roles == {}

    async def test_an_unknown_capability_does_not_block_the_known_ones(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(rbac={"lehrperson": ["user.read", "erfundenes.recht"]}),
            tenant_slug="alpha",
        )
        await db_session.commit()

        assert "erfundenes.recht" in result.unknown_capabilities
        if "lehrperson" in result.changed_roles:
            _, after = result.changed_roles["lehrperson"]
            assert "erfundenes.recht" not in after

    async def test_an_empty_rbac_document_touches_nothing(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """`{}` heisst keine Vorgabe — nicht „nimm allen alles weg".

        Der Unterschied ist in der Konsole eine Spalte, die `NULL` sein darf.
        Hier ist er die Zeile, die eine Installation nicht entrechtet.
        """
        from magister_api.services.rbac import RbacService

        before = await RbacService(db_session).capabilities_by_role()

        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(rbac={}), tenant_slug="alpha"
        )
        await db_session.commit()

        after = await RbacService(db_session).capabilities_by_role()
        assert result.changed_roles == {}
        assert {k: sorted(v) for k, v in after.items()} == {k: sorted(v) for k, v in before.items()}
