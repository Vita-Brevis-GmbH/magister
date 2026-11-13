"""Helper to enrich GUID-keyed rows with display-name fields from ad_user_cache.

Used by the class-teachers and class-memberships routers so the SPA can
render a friendly label without making a second ``/users`` call (which
KL-level callers can't access). One round-trip per response, regardless
of how many rows are being enriched.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache, LoginAccount
from magister_api.repositories.auth import LoginAccountRepository

T = TypeVar("T")


class UserLabelFields(TypedDict):
    """The display fields every GUID-keyed ``*Out`` schema carries."""

    display_name: str | None
    given_name: str | None
    surname: str | None
    upn: str | None


def user_label_fields(label: AdUserCache | None) -> UserLabelFields:
    """Splat-ready label fields for a cached AD user (all None if unknown).

    Use as ``SomeOut(..., **user_label_fields(labels.get(guid)))`` so the
    four-field copy doesn't get repeated at every enrichment call site.
    """
    return UserLabelFields(
        display_name=label.display_name if label else None,
        given_name=label.given_name if label else None,
        surname=label.surname if label else None,
        upn=label.upn if label else None,
    )


async def fetch_user_labels(
    session: AsyncSession,
    guids: Iterable[str],
) -> dict[str, AdUserCache]:
    """Return ``{ad_object_guid: AdUserCache}`` for the given guids.

    # scope-bypass: the caller is already scope-checked at the class level
    # (require_class_writer / require_schulleitung); this look-up is only
    # there to add a display label and never widens visibility.
    """
    guid_list = list({g for g in guids if g})
    if not guid_list:
        return {}
    stmt = select(AdUserCache).where(AdUserCache.ad_object_guid.in_(guid_list))
    result = await session.execute(stmt)
    return {row.ad_object_guid: row for row in result.scalars().all()}


def login_account_label_fields(account: LoginAccount) -> UserLabelFields:
    """Label fields for a Keycloak login account without an AD row (ADR-0025)."""
    return UserLabelFields(
        display_name=account.display_name,
        given_name=None,
        surname=None,
        upn=account.username,
    )


async def fetch_principal_labels(
    session: AsyncSession,
    guids: Iterable[str],
) -> dict[str, UserLabelFields]:
    """Labels for role holders: the AD row first, else the login account.

    Seit ADR-0025 kann eine Rolle an einem Konto hängen, das nur in Keycloak
    steht (etwa ``automato-admin``). Ohne den zweiten Blick stünde es in der
    Rollenliste als „?".
    """
    guid_list = list({g for g in guids if g})
    ad_rows = await fetch_user_labels(session, guid_list)
    out: dict[str, UserLabelFields] = {g: user_label_fields(r) for g, r in ad_rows.items()}
    missing = [g for g in guid_list if g not in out]
    for account in await LoginAccountRepository(session).list_by_principals(missing):
        out[account.principal_guid] = login_account_label_fields(account)
    return out


__all__ = [
    "UserLabelFields",
    "fetch_principal_labels",
    "fetch_user_labels",
    "login_account_label_fields",
    "user_label_fields",
]
