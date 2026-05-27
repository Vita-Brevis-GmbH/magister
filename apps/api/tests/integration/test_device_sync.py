"""Device-name sync from AD's Computer-OU.

End-to-end coverage for Phase 4:
- ``AdClient.search_managed_computers`` returns a ``{user_dn: cn}`` map.
- The sync service merges that map into ``AdUserRecord.device_name``
  before upserting into ``ad_user_cache``.
- Audit payload reports ``device_count``.
- An unset computer-search-base is a soft-no-op (no error, no device data).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.services.ad_sync import AdSyncService

if TYPE_CHECKING:
    from ldap3 import Connection
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


ANNA_GUID = "11111111-1111-1111-1111-1111111111aa"
BENO_GUID = "22222222-2222-2222-2222-2222222222aa"
ANNA_DN = "CN=Anna,OU=Teachers,OU=ALPHA,DC=schule,DC=local"
BENO_DN = "CN=Beno,OU=Students,OU=ALPHA,DC=schule,DC=local"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


def _seed_user(conn: Connection, *, guid: str, dn: str, upn: str) -> None:
    conn.strategy.add_entry(
        dn,
        {
            "objectClass": ["user"],
            "objectGUID": _le(guid),
            "userPrincipalName": upn,
            "userAccountControl": 0x200,
        },
    )


def _seed_computer(conn: Connection, *, cn: str, dn: str, managed_by: str) -> None:
    conn.strategy.add_entry(
        dn,
        {
            "objectClass": ["computer"],
            "cn": cn,
            "name": cn,
            "managedBy": managed_by,
        },
    )


@pytest_asyncio.fixture
async def mock_ad_with_devices(app_settings: Settings):
    settings = app_settings.model_copy(
        update={
            "ad_use_mock": True,
            "ad_users_search_base": "DC=schule,DC=local",
            "ad_computers_search_base": "OU=Computers,DC=schule,DC=local",
        }
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    _seed_user(conn, guid=ANNA_GUID, dn=ANNA_DN, upn="anna@schule.local")
    _seed_user(conn, guid=BENO_GUID, dn=BENO_DN, upn="beno@schule.local")
    _seed_computer(
        conn,
        cn="LAPTOP-ANNA01",
        dn="CN=LAPTOP-ANNA01,OU=Computers,DC=schule,DC=local",
        managed_by=ANNA_DN,
    )
    # Beno has no managed computer — device_name stays None.
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def mock_ad_no_computer_base(app_settings: Settings):
    """Same users as above but without a computer-search-base configured."""
    settings = app_settings.model_copy(
        update={
            "ad_use_mock": True,
            "ad_users_search_base": "DC=schule,DC=local",
        }
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    _seed_user(conn, guid=ANNA_GUID, dn=ANNA_DN, upn="anna@schule.local")
    yield client
    await client.aclose()


class TestSearchManagedComputers:
    @pytest.mark.asyncio
    async def test_returns_dn_to_device_name_map(self, mock_ad_with_devices: AdClient) -> None:
        m = await mock_ad_with_devices.search_managed_computers()
        # Keys are lowercased DNs.
        assert m == {ANNA_DN.lower(): "LAPTOP-ANNA01"}

    @pytest.mark.asyncio
    async def test_empty_base_returns_empty_map(self, mock_ad_no_computer_base: AdClient) -> None:
        m = await mock_ad_no_computer_base.search_managed_computers()
        assert m == {}


class TestSyncMergesDevice:
    @pytest.mark.asyncio
    async def test_device_lands_in_ad_user_cache(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        mock_ad_with_devices: AdClient,
        engine: AsyncEngine,
    ) -> None:
        svc = AdSyncService(db_session, app_settings, mock_ad_with_devices)
        result = await svc.sync_all(
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        await db_session.commit()
        assert result.synced_count == 2
        assert result.device_count == 1

        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            anna = await s.get(AdUserCache, ANNA_GUID)
            beno = await s.get(AdUserCache, BENO_GUID)
        assert anna is not None and anna.device_name == "LAPTOP-ANNA01"
        assert beno is not None and beno.device_name is None

    @pytest.mark.asyncio
    async def test_audit_records_device_count(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        mock_ad_with_devices: AdClient,
        engine: AsyncEngine,
    ) -> None:
        svc = AdSyncService(db_session, app_settings, mock_ad_with_devices)
        await svc.sync_all(
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        await db_session.commit()
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = (
                (
                    await s.execute(
                        select(AuditEvent)
                        .where(AuditEvent.action == "ad_sync_completed")
                        .order_by(AuditEvent.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert row is not None
            event = await AuditService(s, app_settings).read(row.id)
        assert event is not None
        assert event.payload["device_count"] == 1


class TestSyncWithoutComputerBase:
    @pytest.mark.asyncio
    async def test_unset_base_is_silent_no_op(
        self,
        db_session: AsyncSession,
        app_settings: Settings,
        mock_ad_no_computer_base: AdClient,
        engine: AsyncEngine,
    ) -> None:
        svc = AdSyncService(db_session, app_settings, mock_ad_no_computer_base)
        result = await svc.sync_all(
            actor_upn="admin@example.ch",
            actor_object_guid=None,
            ip=None,
            request_id="r1",
        )
        await db_session.commit()
        assert result.synced_count == 1
        assert result.device_count == 0

        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            anna = await s.get(AdUserCache, ANNA_GUID)
        assert anna is not None and anna.device_name is None
