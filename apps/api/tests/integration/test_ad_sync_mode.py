"""Voll oder inkrementell — wer das entscheidet und woran (ADR-0022 D3).

Bis hierher lief der wiederkehrende Abgleich **immer** voll: der Scheduler rief
`sync_all()` ohne `mode` auf, und die Vorgabe war `"full"`. `last_full_sync_at`
wurde dabei geschrieben und nie gelesen — obwohl der Docstring von
`AdSyncState` seit ADR-0004 behauptete, der Scheduler erzwinge darüber den
periodischen Vollabgleich.

Ohne Connector war das eine Unhöflichkeit gegenüber dem Domänencontroller. Mit
Connector ist es ein Fehler: das ganze Verzeichnis, alle fünfzehn Minuten,
durch eine Auftragswarteschlange.

Geprüft wird hier am Verhalten (welcher Cursor geht an das Verzeichnis), nicht
an einem Rückgabewert: genau dieser Aufruf ist die Übertragung, um die es geht.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.config import Settings
from magister_api.models.ad_sync_state import AdSyncState
from magister_api.services.ad_sync import AdSyncService

pytestmark = pytest.mark.postgres

WHEN = datetime(2026, 9, 11, 6, 0, tzinfo=UTC)


class RecordingAd(AdClient):
    """Ein Verzeichnis, das nichts liefert, aber mitschreibt, wonach gefragt wurde."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[datetime | None] = []

    async def search_users(self, **kwargs: object) -> list[AdUserRecord]:  # type: ignore[override]
        changed_since = kwargs.get("changed_since")
        self.calls.append(changed_since if isinstance(changed_since, datetime) else None)
        return []

    async def search_managed_computers(self, **kwargs: object) -> dict[str, str]:  # type: ignore[override]
        return {}

    async def search_computers(self, **kwargs: object) -> list[object]:  # type: ignore[override]
        return []

    async def aclose(self) -> None:
        return None


async def _state(session: AsyncSession) -> AdSyncState:
    state = await session.get(AdSyncState, 1)
    if state is None:
        state = AdSyncState(id=1)
        session.add(state)
        await session.flush()
    return state


async def _run(
    session: AsyncSession, settings: Settings, ad: RecordingAd, *, mode: str = "incremental"
) -> None:
    await AdSyncService(session, settings, ad).sync_all(
        actor_upn="system:test",
        actor_object_guid=None,
        ip=None,
        request_id="r-1",
        mode=mode,  # type: ignore[arg-type]
    )


@pytest.fixture
def settings(app_settings: Settings) -> Settings:
    return app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )


class TestTheModeDecision:
    @pytest.mark.asyncio
    async def test_the_first_run_is_full_even_when_incremental_was_asked(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Ohne Cursor gibt es nichts, wovon aus gelesen werden könnte."""
        ad = RecordingAd(settings)
        await _run(db_session, settings, ad)
        assert ad.calls == [None]

    @pytest.mark.asyncio
    async def test_the_next_run_uses_the_cursor(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        state = await _state(db_session)
        state.last_when_changed = WHEN
        state.last_full_sync_at = datetime.now(UTC) - timedelta(hours=1)
        await db_session.flush()

        ad = RecordingAd(settings)
        await _run(db_session, settings, ad)
        assert ad.calls == [WHEN], "der wiederkehrende Lauf holt wieder das ganze Verzeichnis"

    @pytest.mark.asyncio
    async def test_a_stale_full_run_makes_the_next_one_full(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """`whenChanged` zeigt keine Löschungen — deshalb der Takt.

        Ein gelöschtes Konto hat keinen Änderungszeitpunkt mehr. Ohne
        regelmässigen Vollabgleich bliebe es für immer im Cache und damit in
        der Klassenliste, aus der jemand Passwörter setzt.
        """
        state = await _state(db_session)
        state.last_when_changed = WHEN
        state.last_full_sync_at = datetime.now(UTC) - timedelta(hours=25)
        await db_session.flush()

        ad = RecordingAd(settings)
        await _run(db_session, settings, ad)
        assert ad.calls == [None]

    @pytest.mark.asyncio
    async def test_a_cursor_without_a_full_run_is_not_trusted(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        state = await _state(db_session)
        state.last_when_changed = WHEN
        state.last_full_sync_at = None
        await db_session.flush()

        ad = RecordingAd(settings)
        await _run(db_session, settings, ad)
        assert ad.calls == [None]

    @pytest.mark.asyncio
    async def test_zero_hours_means_every_run_is_full(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Der ausdrückliche Rückweg auf das Verhalten vor ADR-0022."""
        state = await _state(db_session)
        state.last_when_changed = WHEN
        state.last_full_sync_at = datetime.now(UTC)
        await db_session.flush()

        never_incremental = settings.model_copy(update={"ad_full_sync_hours": 0})
        ad = RecordingAd(never_incremental)
        await _run(db_session, never_incremental, ad)
        assert ad.calls == [None]

    @pytest.mark.asyncio
    async def test_an_explicit_full_run_stays_full(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        state = await _state(db_session)
        state.last_when_changed = WHEN
        state.last_full_sync_at = datetime.now(UTC)
        await db_session.flush()

        ad = RecordingAd(settings)
        await _run(db_session, settings, ad, mode="full")
        assert ad.calls == [None]


class TestTheLongReadKeepsItsSession:
    @pytest.mark.asyncio
    async def test_the_idle_limit_is_raised_for_the_directory_read(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """ADR-0021 D3 setzt 60 s Leerlauf — der Abgleich braucht mehr.

        Die Transaktion steht offen, während das Verzeichnis gelesen wird; bei
        einem gehosteten Kunden über den Agenten sind das Minuten. Ohne das
        Anheben beendet Postgres die Sitzung mitten im Lauf, und im Protokoll
        stünde ein Datenbankfehler, wo ein langsames AD steht.
        """
        seen: list[str] = []

        class Watching(RecordingAd):
            async def search_users(self, **kwargs: object) -> list[AdUserRecord]:
                row = await db_session.execute(text("SHOW idle_in_transaction_session_timeout"))
                seen.append(str(row.scalar_one()))
                return await super().search_users(**kwargs)

        ad = Watching(settings)
        await _run(db_session, settings, ad)
        # 900 000 ms — Postgres zeigt sie als "15min".
        assert seen == ["15min"], f"Leerlauf-Grenze während des Laufs: {seen}"

    @pytest.mark.asyncio
    async def test_the_limit_cannot_be_configured_below_a_minute(self, settings: Settings) -> None:
        """Die Grenze wird angehoben, nicht abgeschafft.

        Eine Einstellung, mit der man sie unter die 60 Sekunden aus ADR-0021
        D3 drücken kann, wäre ein Weg, diese Grenze über eine Umgebung
        auszuhebeln — und niemand würde es merken.
        """
        with pytest.raises(ValidationError):
            settings.model_copy(update={"ad_sync_transaction_idle_ms": 1_000}).model_validate(
                settings.model_dump() | {"ad_sync_transaction_idle_ms": 1_000}
            )
