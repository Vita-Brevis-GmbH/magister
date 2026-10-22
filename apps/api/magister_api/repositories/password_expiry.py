"""Passwort-Ablauf im Sichtbereich: bald fällig, und Konten ohne Mailadresse."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.group_template import GroupTemplate
from magister_api.models.password_expiry_notice import PasswordExpiryNotice
from magister_api.repositories.base import BaseRepository, ScopeContext

#: Mehr zeigt die Übersicht nicht auf einmal — sie ist eine Arbeitsliste.
MAX_ROWS = 2000


class PasswordExpiryRepository(BaseRepository):
    def __init__(self, session: AsyncSession, scope: ScopeContext) -> None:
        super().__init__(session, scope)

    def _base(self, school_id: int | None) -> Select[tuple[AdUserCache, str | None]]:
        stmt = (
            select(AdUserCache, GroupTemplate.name)
            .outerjoin(GroupTemplate, GroupTemplate.id == AdUserCache.group_template_id)
            .where(AdUserCache.enabled.is_(True), AdUserCache.ad_missing_since.is_(None))
        )
        if school_id is not None:
            stmt = stmt.where(AdUserCache.school_id == school_id)
        return self.apply_scope(stmt, AdUserCache.school_id)

    async def expiring(
        self, *, now: datetime, within_days: int, school_id: int | None = None
    ) -> list[tuple[AdUserCache, str | None]]:
        """Läuft in den nächsten ``within_days`` Tagen ab — oder ist schon abgelaufen."""
        stmt = (
            self._base(school_id)
            .where(
                AdUserCache.password_never_expires.is_(False),
                AdUserCache.password_expires_at.is_not(None),
                AdUserCache.password_expires_at <= now + timedelta(days=within_days),
            )
            .order_by(AdUserCache.password_expires_at)
            .limit(MAX_ROWS)
        )
        return [(u, name) for u, name in (await self.session.execute(stmt)).all()]

    async def without_mail(
        self, *, school_id: int | None = None
    ) -> list[tuple[AdUserCache, str | None]]:
        """Aktive Konten ohne Mailadresse — die Erinnerung erreicht sie nicht."""
        stmt = (
            self._base(school_id)
            .where(or_(AdUserCache.mail.is_(None), AdUserCache.mail == ""))
            .order_by(
                AdUserCache.password_expires_at.asc().nulls_last(),
                AdUserCache.surname,
                AdUserCache.given_name,
            )
            .limit(MAX_ROWS)
        )
        return [(u, name) for u, name in (await self.session.execute(stmt)).all()]

    async def by_age(
        self,
        *,
        oldest_first: bool,
        offset: int,
        limit: int,
        school_id: int | None = None,
    ) -> tuple[list[tuple[AdUserCache, str | None]], int]:
        """Alle aktiven Konten nach Passwortalter (``password_last_set``), seitenweise.

        Ohne Datum (Änderung bei der nächsten Anmeldung verlangt, oder noch
        nicht gelesen) stehen immer am Schluss.
        """
        base = self._base(school_id)
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        order = (
            AdUserCache.password_last_set.asc().nulls_last()
            if oldest_first
            else AdUserCache.password_last_set.desc().nulls_last()
        )
        stmt = (
            base.order_by(order, AdUserCache.surname, AdUserCache.given_name)
            .offset(offset)
            .limit(min(limit, MAX_ROWS))
        )
        rows = [(u, name) for u, name in (await self.session.execute(stmt)).all()]
        return rows, int(total)

    async def last_notices(self, users: list[AdUserCache]) -> dict[str, PasswordExpiryNotice]:
        """Die jüngste Erinnerung je Konto — nur für dessen aktuellen Ablauf."""
        current = {u.ad_object_guid: u.password_expires_at for u in users if u.password_expires_at}
        if not current:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(PasswordExpiryNotice).where(
                        PasswordExpiryNotice.ad_object_guid.in_(list(current))
                    )
                )
            )
            .scalars()
            .all()
        )
        latest: dict[str, PasswordExpiryNotice] = {}
        for row in rows:
            if row.expires_at != current.get(row.ad_object_guid):
                continue
            have = latest.get(row.ad_object_guid)
            if have is None or row.created_at > have.created_at:
                latest[row.ad_object_guid] = row
        return latest
