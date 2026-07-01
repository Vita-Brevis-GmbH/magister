"""Self-service preferences orchestration (read + audited write)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.user_preferences import (
    DEFAULT_DATE_FORMAT,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_TIME_FORMAT,
    UserPreference,
)
from magister_api.repositories.user_preferences import UserPreferenceRepository
from magister_api.schemas.user_preferences import UserPreferencesOut, UserPreferencesUpdate


def _defaults() -> UserPreferencesOut:
    return UserPreferencesOut(
        language=DEFAULT_LANGUAGE,  # type: ignore[arg-type]
        region=DEFAULT_REGION,
        date_format=DEFAULT_DATE_FORMAT,  # type: ignore[arg-type]
        time_format=DEFAULT_TIME_FORMAT,  # type: ignore[arg-type]
    )


class UserPreferenceService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.repo = UserPreferenceRepository(session)
        self.audit = AuditService(session, settings)

    async def get(self, ad_object_guid: str) -> UserPreferencesOut:
        row = await self.repo.get(ad_object_guid)
        return UserPreferencesOut.model_validate(row) if row is not None else _defaults()

    async def update(
        self,
        *,
        ad_object_guid: str,
        actor_upn: str,
        payload: UserPreferencesUpdate,
        ip: str | None,
        request_id: str,
    ) -> UserPreferencesOut:
        row: UserPreference = await self.repo.upsert(
            ad_object_guid=ad_object_guid,
            language=payload.language,
            region=payload.region,
            date_format=payload.date_format,
            time_format=payload.time_format,
        )
        await self.audit.emit(
            action="user_preferences_updated",
            target_kind="user_preferences",
            target_id=ad_object_guid,
            actor_upn=actor_upn,
            actor_object_guid=ad_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload={
                "language": payload.language,
                "region": payload.region,
                "date_format": payload.date_format,
                "time_format": payload.time_format,
            },
        )
        return UserPreferencesOut.model_validate(row)


__all__ = ["UserPreferenceService"]
