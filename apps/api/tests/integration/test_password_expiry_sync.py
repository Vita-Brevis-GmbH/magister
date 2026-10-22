"""AD-Abgleich: Kennwort-Ablauf landet im Cache; ohne Angabe bleibt der alte Stand."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdUserRecord
from magister_api.models.auth import AdUserCache
from magister_api.repositories.ad_users import AdUserCacheSyncRepository

pytestmark = pytest.mark.postgres

GUID = "00000000-0000-0000-0000-0000000f0001"


def _rec(**extra: object) -> AdUserRecord:
    base = AdUserRecord(
        ad_object_guid=GUID,
        upn="lea@schule.ch",
        sam_account_name="lea",
        given_name="Lea",
        surname="Muster",
        display_name=None,
        mail="lea@schule.ch",
        enabled=True,
        kind="teacher",
        password_never_expires=False,
        ms_ds_consistency_guid=None,
        distinguished_name="CN=Lea,OU=A,DC=schule,DC=local",
        street_address=None,
        locality=None,
        postal_code=None,
        country=None,
    )
    return dataclasses.replace(base, **extra)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_expiry_is_stored_and_kept_when_the_source_does_not_know(
    db_session: AsyncSession, school_a: int
) -> None:
    repo = AdUserCacheSyncRepository(db_session)
    expires = datetime(2026, 11, 30, 8, 0, tzinfo=UTC)
    await repo.upsert_from_ad(
        [
            _rec(
                password_info=True,
                password_last_set=datetime(2026, 9, 1, tzinfo=UTC),
                password_expires_at=expires,
            )
        ],
        school_id_resolver=lambda _r: school_a,
    )
    await db_session.commit()

    # Älterer Agent: keine Angabe → der bekannte Ablauf bleibt.
    await repo.upsert_from_ad([_rec()], school_id_resolver=lambda _r: school_a)
    await db_session.commit()
    db_session.expire_all()
    row = await db_session.get(AdUserCache, GUID)
    assert row is not None
    assert row.password_expires_at == expires
    assert row.password_info_at is not None

    # Neues Kennwort gesetzt, läuft jetzt nie ab: wird übernommen.
    await repo.upsert_from_ad(
        [_rec(password_info=True, password_last_set=datetime(2026, 10, 1, tzinfo=UTC))],
        school_id_resolver=lambda _r: school_a,
    )
    await db_session.commit()
    db_session.expire_all()
    row = await db_session.get(AdUserCache, GUID)
    assert row is not None
    assert row.password_expires_at is None
    assert row.password_last_set == datetime(2026, 10, 1, tzinfo=UTC)
