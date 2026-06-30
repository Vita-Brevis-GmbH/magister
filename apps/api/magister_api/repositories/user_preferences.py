"""Repository for per-user preferences (keyed by the caller's objectGUID).

# scope-bypass: a preferences row is keyed by, and only ever read/written for,
# the authenticated caller's own objectGUID — there is no cross-user access and
# no school-scoped personal data here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.user_preferences import UserPreference


class UserPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, ad_object_guid: str) -> UserPreference | None:
        return await self.session.get(UserPreference, ad_object_guid)

    async def upsert(
        self,
        *,
        ad_object_guid: str,
        language: str,
        region: str,
        date_format: str,
        time_format: str,
    ) -> UserPreference:
        row = await self.session.get(UserPreference, ad_object_guid)
        if row is None:
            row = UserPreference(ad_object_guid=ad_object_guid)
            self.session.add(row)
        row.language = language
        row.region = region
        row.date_format = date_format
        row.time_format = time_format
        await self.session.flush()
        return row


__all__ = ["UserPreferenceRepository"]
