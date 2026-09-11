"""Der periodische AD-Abgleich — je Kunde, versetzt, isoliert (ADR-0021 D4).

Treibt :func:`run_ad_sync_loop` gegen ldap3 ``MOCK_SYNC`` und echtes Postgres
und prüft, dass ohne Zutun ``ad_user_cache`` gefüllt und
``ad_sync_completed`` geschrieben wird.

Dazu die Zusagen, die ADR-0021 D4 neu macht:

* **Jeder Kunde kommt dran.** Bis dahin nahm die Schleife eine Sitzung aus der
  Prozess-Engine und synchronisierte genau ein Schema — bei zwei Kunden einen
  und den anderen nicht, und zwar still. Der Test mit zwei Mandanten ist
  deshalb der eigentliche Punkt dieser Datei.
* **Einer, der stolpert, hält die anderen nicht auf.**
* **Die Startzeiten sind versetzt**, deterministisch und nicht zufällig.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.services import ad_sync_scheduler
from magister_api.services.ad_sync_scheduler import (
    TICK_SECONDS,
    _initial_due,
    run_ad_sync_loop,
)
from magister_api.tenancy.registry import Tenant, TenantRegistry, TenantStatus

pytestmark = pytest.mark.postgres

DORA_GUID = "44444444-4444-4444-4444-444444444444"


def _le(guid_str: str) -> bytes:
    return uuid.UUID(guid_str).bytes_le


def _sole_tenant(database_url: str) -> Tenant:
    """Der Einmandanten-Fall: Schema `public`, keine eigene Rolle.

    So sieht eine Einzelinstallation aus, und so sieht die
    Integrationsumgebung aus — sie hat genau ein Schema.
    """
    return Tenant(
        slug="testkunde",
        name="Testkunde",
        dsn=database_url,
        schema_name="public",
        db_role=None,
        schema_version="",
        status=TenantStatus.ACTIVE,
    )


def _tenant(slug: str, database_url: str) -> Tenant:
    """Ein Mandant in der Form, die die Registry ab zwei Kunden verlangt.

    Eigene Rolle, eigenes Schema, eigener Hostname — und ein DSN, der sich
    **mit dieser Rolle** anmeldet. Sonst weist `TenantRegistry` die Sammlung
    zurück: zwei Mandanten auf derselben Anmelderolle könnten per `SET ROLE`
    ineinander wechseln (ADR-0013 D1), und dass sie das zu Recht nicht
    zulässt, ist beim Schreiben dieses Tests aufgefallen.
    """
    dsn = (
        make_url(database_url)
        .set(username=f"r_{slug}", password="egal")
        .render_as_string(hide_password=False)
    )
    return Tenant(
        slug=slug,
        name=slug.title(),
        dsn=dsn,
        schema_name=f"t_{slug}",
        db_role=f"r_{slug}",
        schema_version="",
        status=TenantStatus.ACTIVE,
        hostname=f"{slug}.magister.test",
    )


@pytest.fixture
def all_due_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Den Versatz für diesen Test abschalten.

    Der Versatz ist richtig und hat seinen eigenen Test (`TestTheStagger`):
    bei zwei Kunden und 15 Minuten Intervall ist der zweite erst in
    siebeneinhalb Minuten fällig. Ein Test, der darauf wartet, wäre kein Test.
    Hier interessiert die andere Zusage — **dass jeder Kunde dran kommt** —,
    und die lässt sich nur ohne Versatz in Sekunden beobachten.
    """
    monkeypatch.setattr(
        ad_sync_scheduler,
        "_initial_due",
        lambda now, tenants, interval_minutes: {t.slug: now for t in tenants},
    )


@pytest.fixture
def tenant_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kundenschlüssel für die beiden Test-Mandanten.

    Ab zwei Mandanten gelten die mandantenlosen Einstellungen **nicht** mehr
    (ADR-0016 D8) — `resolve_tenant_keys` verlangt dann je Kunde einen
    eigenen Schlüssel, und ohne ihn kommt die Schleife nicht einmal bis zur
    Sitzung. Genau das ist beim Schreiben dieses Tests aufgefallen: ohne diese
    Fixture prüfte er still nichts.
    """
    for slug in ("alpha", "beta", "kaputt", "gesund"):
        ref = slug.upper()
        # Mindestens 32 Zeichen — `resolve_tenant_keys` weist kürzere ab,
        # und das zu Recht.
        monkeypatch.setenv(f"MAGISTER_TENANT_AUDIT_KEY_{ref}", f"audit-key-{slug}".ljust(40, "x"))
        monkeypatch.setenv(f"MAGISTER_TENANT_AUDIT_KEY_ID_{ref}", f"key-{slug}")
        monkeypatch.setenv(
            f"MAGISTER_TENANT_SECRETS_KEY_{ref}", f"secrets-key-{slug}".ljust(40, "x")
        )


@pytest_asyncio.fixture
async def seeded_mock_client(app_settings: Settings) -> AsyncIterator[AdClient]:
    """Ein AdClient auf einer MOCK_SYNC-Verbindung mit einem Schüler."""
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    conn.strategy.add_entry(
        "CN=Dora,OU=Students,OU=ALPHA,DC=schule,DC=local",
        {
            "objectClass": ["user"],
            "objectGUID": _le(DORA_GUID),
            "userPrincipalName": "dora@example.ch",
            "givenName": "Dora",
            "sn": "D.",
            "mail": "dora@example.ch",
            "userAccountControl": 0x200,
            "memberOf": [],
        },
    )
    yield client
    await client.aclose()


async def _until(condition: Callable[[], bool], timeout_s: float = 5.0) -> None:
    """Warten, bis *condition* zutrifft — oder bis die Frist abläuft.

    Kein `asyncio.Event`: was hier beobachtet wird, ist eine Liste, die eine
    injizierte Fabrik füllt. Ein Event dafür wäre ein zweiter Zustand, der mit
    dem ersten auseinanderlaufen kann.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline and not condition():  # noqa: ASYNC110
        await asyncio.sleep(0.05)


async def _wait_for_cached_upn(engine: AsyncEngine, upn: str, timeout_s: float = 5.0) -> bool:
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        async with sm() as s:
            found = (
                await s.execute(select(AdUserCache.upn).where(AdUserCache.upn == upn))
            ).scalar_one_or_none()
        if found is not None:
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.asyncio
async def test_loop_populates_cache_and_audits(
    engine: AsyncEngine,
    app_settings: Settings,
    database_url: str,
    seeded_mock_client: AdClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(School(name="Schule Alpha", kuerzel="ALPHA", scope_short="ALPHA"))
    await db_session.commit()

    base = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    registry = TenantRegistry([_sole_tenant(database_url)])
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_ad_sync_loop(
            base,
            stop_event=stop,
            client_factory=lambda _s: seeded_mock_client,
            read_registry=lambda: registry,
            session_factory=lambda _t: sm,
        )
    )
    try:
        assert await _wait_for_cached_upn(engine, "dora@example.ch"), "Cache blieb leer"
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async with sm() as s:
        actions = list((await s.execute(select(AuditEvent.action))).scalars().all())
        actor = (
            await s.execute(
                select(AuditEvent.actor_upn).where(AuditEvent.action == "ad_sync_completed")
            )
        ).scalar_one()
    assert "ad_sync_completed" in actions
    assert actor == "system:ad-sync-scheduler"


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_keys", "all_due_now")
async def test_every_tenant_is_synced_not_just_the_first(
    engine: AsyncEngine,
    app_settings: Settings,
    database_url: str,
    seeded_mock_client: AdClient,
    db_session: AsyncSession,
) -> None:
    """Der Fehler, den ADR-0021 D4 behebt.

    Was dieser Test prüft, ist genau eines: **die Schleife fasst beide an.**
    Vorher bekam der zweite Kunde nie einen Aufruf, und das war der Fehler.

    Was er **nicht** prüft: dass der Abgleich für beide durchläuft. Die
    Integrationsumgebung hat ein Schema, nicht zwei; die zwei Mandanten hier
    zeigen auf `t_alpha`/`t_beta`, die es nicht gibt, und scheitern
    anschliessend an der Scope-Zusicherung. Dass ein Abgleich über die
    Schleife wirklich läuft, steht im Test darüber; dass der Scope trennt, in
    `test_tenant_isolation.py`.
    """
    db_session.add(School(name="Schule Alpha", kuerzel="ALPHA", scope_short="ALPHA"))
    await db_session.commit()

    base = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    registry = TenantRegistry([_tenant("alpha", database_url), _tenant("beta", database_url)])
    touched: list[str] = []

    def _factory(tenant: Tenant) -> async_sessionmaker[AsyncSession]:
        touched.append(tenant.slug)
        return sm

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_ad_sync_loop(
            base,
            stop_event=stop,
            client_factory=lambda _s: seeded_mock_client,
            read_registry=lambda: registry,
            session_factory=_factory,
        )
    )
    try:
        await _until(lambda: len(set(touched)) >= 2)
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert set(touched) == {"alpha", "beta"}, touched


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_keys", "all_due_now")
async def test_one_broken_tenant_does_not_stop_the_others(
    engine: AsyncEngine,
    app_settings: Settings,
    database_url: str,
    seeded_mock_client: AdClient,
) -> None:
    """Dieselbe Zusage wie beim Abgleich des Soll-Zustands."""
    base = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    registry = TenantRegistry([_tenant("kaputt", database_url), _tenant("gesund", database_url)])
    reached: list[str] = []

    def _factory(tenant: Tenant) -> async_sessionmaker[AsyncSession]:
        reached.append(tenant.slug)
        if tenant.slug == "kaputt":
            raise RuntimeError("Engine für diesen Kunden ist unbrauchbar")
        return sm

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_ad_sync_loop(
            base,
            stop_event=stop,
            client_factory=lambda _s: seeded_mock_client,
            read_registry=lambda: registry,
            session_factory=_factory,
        )
    )
    try:
        await _until(lambda: "gesund" in reached)
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert "gesund" in reached, reached


@pytest.mark.asyncio
async def test_loop_skips_when_ad_unconfigured(
    engine: AsyncEngine,
    app_settings: Settings,
    database_url: str,
) -> None:
    base = app_settings.model_copy(
        update={"ad_use_mock": False, "ad_dcs": [], "ad_users_search_base": None}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    registry = TenantRegistry([_sole_tenant(database_url)])
    stop = asyncio.Event()

    def _explode(_s: Settings) -> AdClient:
        raise AssertionError("AD-Client gebaut, obwohl AD nicht konfiguriert ist")

    task = asyncio.create_task(
        run_ad_sync_loop(
            base,
            stop_event=stop,
            client_factory=_explode,
            read_registry=lambda: registry,
            session_factory=lambda _t: sm,
        )
    )
    # Zeit für mindestens eine (übersprungene) Runde.
    await asyncio.sleep(0.3)
    stop.set()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    async with sm() as s:
        audit_count = (await s.execute(select(func.count()).select_from(AuditEvent))).scalar_one()
    assert audit_count == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_keys")
async def test_a_tenant_that_appears_later_is_due_at_once(
    engine: AsyncEngine,
    app_settings: Settings,
    database_url: str,
    seeded_mock_client: AdClient,
) -> None:
    """Ein neuer Kunde wartet nicht auf seinen Platz in der Verteilung.

    Der Versatz gilt für die erste Runde. Wer später dazukommt, hat noch
    keine Daten — ihn bis zu ein Intervall warten zu lassen, wäre eine
    Wartezeit ohne Grund. Und die Termine der anderen verschieben sich dabei
    nicht.
    """
    base = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    first = TenantRegistry([_tenant("alpha", database_url)])
    both = TenantRegistry([_tenant("alpha", database_url), _tenant("beta", database_url)])
    state = {"registry": first}
    touched: list[str] = []

    def _factory(tenant: Tenant) -> async_sessionmaker[AsyncSession]:
        touched.append(tenant.slug)
        return sm

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_ad_sync_loop(
            base,
            stop_event=stop,
            client_factory=lambda _s: seeded_mock_client,
            read_registry=lambda: state["registry"],
            session_factory=_factory,
        )
    )
    try:
        await _until(lambda: "alpha" in touched)
        # Jetzt taucht beta auf — und muss in der nächsten Runde dran sein,
        # nicht in siebeneinhalb Minuten.
        state["registry"] = both
        await _until(lambda: "beta" in touched, timeout_s=TICK_SECONDS * 3)
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert "beta" in touched, touched


class TestTheStagger:
    def test_the_first_runs_now_and_the_rest_are_spread(self, database_url: str) -> None:
        tenants = [_tenant(f"k{i}", database_url) for i in range(4)]
        due = _initial_due(1000.0, tenants, interval_minutes=60)
        # Der erste sofort, die übrigen in Viertelstunden-Abstand.
        assert due["k0"] == 1000.0
        assert due["k1"] == 1000.0 + 900.0
        assert due["k2"] == 1000.0 + 1800.0
        assert due["k3"] == 1000.0 + 2700.0

    def test_a_single_tenant_has_no_offset(self, database_url: str) -> None:
        """Einzelinstallation: derselbe Fahrplan wie vor ADR-0021."""
        due = _initial_due(500.0, [_tenant("allein", database_url)], interval_minutes=15)
        assert due == {"allein": 500.0}

    def test_no_tenants_is_no_schedule(self) -> None:
        assert _initial_due(0.0, [], interval_minutes=15) == {}

    def test_the_spread_is_deterministic(self, database_url: str) -> None:
        """Zweimal dieselbe Registry, zweimal derselbe Fahrplan.

        Ein Zufallsversatz wäre im Log nicht nachvollziehbar — und die Frage
        „warum hat Kunde 7 um 04:13 synchronisiert" soll eine Antwort haben.
        """
        tenants = [_tenant(f"k{i}", database_url) for i in range(3)]
        assert _initial_due(42.0, tenants, 30) == _initial_due(42.0, tenants, 30)
