"""Befunde über die Connector-Flotte (ADR-0021 D6).

Der Unterschied zwischen Anzeigen und Überwachen. Die Konsole zeigte
Zertifikatsablauf und `last_seen_at` schon — aber nur, wenn jemand hinsieht.

Die Schwellen sind hier der Prüfgegenstand, nicht Beiwerk: sie folgen aus dem
Verhalten des Agenten (erneuert 30 Tage vor Ablauf, meldet sich im
Minutentakt), und wenn sie driften, ist der Alarm entweder Lärm oder er kommt
zu spät.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.models import AgentStatus, ConnectorAgent, Tenant, TenantStatus
from cockpit_api.services.fleet import (
    EXIT_CRITICAL,
    EXIT_OK,
    EXIT_WARNING,
    Severity,
    exit_code,
    fleet_findings,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_factory(cockpit_schema: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(cockpit_schema, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _tenant(session: AsyncSession, slug: str, *, status: TenantStatus) -> Tenant:
    tenant = Tenant(
        slug=slug,
        name=slug.title(),
        hostname=f"{slug}.magister.test",
        status=status,
        dsn_ref=slug,
        schema_name=f"t_{slug}",
        db_role=f"r_{slug}",
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def _agent(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str = "dc01",
    days_left: int = 90,
    last_seen: datetime | None = NOW,
    created: datetime | None = None,
    version: str | None = "1.4.0",
    status: AgentStatus = AgentStatus.online,
    revoked: bool = False,
) -> ConnectorAgent:
    agent = ConnectorAgent(
        tenant_id=tenant.id,
        name=name,
        status=status,
        spki_sha256=uuid.uuid4().hex + uuid.uuid4().hex[:0],
        certificate_serial=uuid.uuid4().hex[:16],
        certificate_not_after=NOW + timedelta(days=days_left),
        api_key_hash="argon2-hash",
        result_hmac_key="hmac",
        agent_version=version,
        last_seen_at=last_seen,
        revoked_at=NOW if revoked else None,
        created_at=created or (NOW - timedelta(days=30)),
    )
    session.add(agent)
    await session.flush()
    return agent


@pytest.mark.asyncio
class TestCertificates:
    async def test_a_healthy_certificate_is_no_finding(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            tenant = await _tenant(session, "gesund", status=TenantStatus.active)
            await _agent(session, tenant, days_left=90)
            assert await fleet_findings(session, now=NOW) == []

    async def test_below_the_renewal_window_it_is_overdue_not_expiring(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Der Kern der Schwelle.

        27 Tage Restlaufzeit sind nicht „läuft bald ab" — der Agent hätte drei
        Tage zuvor erneuern müssen. Der Befund heisst deshalb
        `renewal_overdue` und nicht `certificate_expiring`: was kaputt ist, ist
        die Erneuerung, und danach sucht man.
        """
        async with session_factory() as session:
            tenant = await _tenant(session, "faellig", status=TenantStatus.active)
            await _agent(session, tenant, days_left=27)
            found = await fleet_findings(session, now=NOW)
        assert [f.kind for f in found] == ["renewal_overdue"]
        assert found[0].severity is Severity.warning
        assert "30 Tage vorher" in found[0].detail

    async def test_a_week_left_is_critical(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            tenant = await _tenant(session, "knapp", status=TenantStatus.active)
            await _agent(session, tenant, days_left=5)
            found = await fleet_findings(session, now=NOW)
        assert found[0].kind == "renewal_overdue"
        assert found[0].severity is Severity.critical

    async def test_an_expired_certificate_says_what_it_costs(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            tenant = await _tenant(session, "abgelaufen", status=TenantStatus.active)
            await _agent(session, tenant, days_left=-3)
            found = await fleet_findings(session, now=NOW)
        assert found[0].kind == "certificate_expired"
        assert found[0].severity is Severity.critical
        # Ein Befund ohne „und was nun" ist eine Zeile, die man wegklickt.
        assert "Passwort-Resets" in found[0].detail

    async def test_a_revoked_agent_is_not_a_finding(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Ein widerrufenes Zertifikat läuft ab, ohne dass es jemanden angeht.

        Und ein widerrufener Agent, der still ist, ist die Absicht.
        """
        async with session_factory() as session:
            tenant = await _tenant(session, "widerrufen", status=TenantStatus.active)
            await _agent(
                session,
                tenant,
                days_left=-10,
                last_seen=NOW - timedelta(days=40),
                status=AgentStatus.revoked,
                revoked=True,
            )
            found = await fleet_findings(session, now=NOW)
        # Bleibt: der Kunde hat jetzt keinen Agenten mehr.
        assert [f.kind for f in found] == ["tenant_without_agent"]


@pytest.mark.asyncio
class TestContact:
    async def test_five_minutes_of_silence_are_not_an_alarm(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """`STALE_AFTER` ist 5 Minuten — für die Anwendung, nicht für den Alarm.

        Ein Neustart des Kundenservers darf nachts niemanden wecken.
        """
        async with session_factory() as session:
            tenant = await _tenant(session, "neustart", status=TenantStatus.active)
            await _agent(session, tenant, last_seen=NOW - timedelta(minutes=6))
            assert await fleet_findings(session, now=NOW) == []

    async def test_an_hour_of_silence_is_a_finding(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            tenant = await _tenant(session, "still", status=TenantStatus.active)
            await _agent(session, tenant, last_seen=NOW - timedelta(hours=2))
            found = await fleet_findings(session, now=NOW)
        assert found[0].kind == "agent_silent"
        assert found[0].severity is Severity.warning

    async def test_a_day_of_silence_is_critical(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            tenant = await _tenant(session, "tagelang", status=TenantStatus.active)
            await _agent(session, tenant, last_seen=NOW - timedelta(days=3))
            found = await fleet_findings(session, now=NOW)
        assert found[0].kind == "agent_silent"
        assert found[0].severity is Severity.critical

    async def test_a_fresh_agent_that_never_called_is_not_yet_a_finding(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Das Paket ist unterwegs. Erst danach ist es ein hängendes Onboarding."""
        async with session_factory() as session:
            tenant = await _tenant(session, "frisch", status=TenantStatus.active)
            await _agent(
                session, tenant, last_seen=None, created=NOW - timedelta(hours=2), version=None
            )
            assert await fleet_findings(session, now=NOW) == []

    async def test_an_old_agent_that_never_called_is_a_finding(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            tenant = await _tenant(session, "haengt", status=TenantStatus.active)
            await _agent(
                session, tenant, last_seen=None, created=NOW - timedelta(days=4), version=None
            )
            found = await fleet_findings(session, now=NOW)
        assert found[0].kind == "agent_never_seen"
        assert "46200" in found[0].detail


@pytest.mark.asyncio
class TestVersions:
    async def test_one_agent_alone_is_never_behind(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Ohne Vergleich kein Befund — und eine erfundene Sollversion wäre
        eine zweite Wahrheit neben der Flotte."""
        async with session_factory() as session:
            tenant = await _tenant(session, "einzeln", status=TenantStatus.active)
            await _agent(session, tenant, version="1.0.0")
            assert await fleet_findings(session, now=NOW) == []

    async def test_the_one_behind_the_fleet_is_named(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            alt = await _tenant(session, "alt", status=TenantStatus.active)
            neu = await _tenant(session, "neu", status=TenantStatus.active)
            await _agent(session, alt, version="1.3.0")
            await _agent(session, neu, version="1.4.0")
            found = await fleet_findings(session, now=NOW)
        assert [(f.kind, f.tenant_slug) for f in found] == [("agent_version_behind", "alt")]
        assert "1.4.0" in found[0].detail

    async def test_an_even_fleet_is_quiet(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            a = await _tenant(session, "eins", status=TenantStatus.active)
            b = await _tenant(session, "zwei", status=TenantStatus.active)
            await _agent(session, a, version="1.4.0")
            await _agent(session, b, version="1.4.0")
            assert await fleet_findings(session, now=NOW) == []


@pytest.mark.asyncio
class TestGaps:
    async def test_an_active_tenant_without_an_agent_is_a_finding(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            await _tenant(session, "ohne", status=TenantStatus.active)
            found = await fleet_findings(session, now=NOW)
        assert [f.kind for f in found] == ["tenant_without_agent"]

    async def test_a_suspended_tenant_without_an_agent_is_not(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            await _tenant(session, "gesperrt", status=TenantStatus.suspended)
            assert await fleet_findings(session, now=NOW) == []


class TestTheExitCode:
    def test_nothing_is_zero(self) -> None:
        assert exit_code([]) == EXIT_OK

    def test_the_worst_wins(self) -> None:
        from cockpit_api.services.fleet import Finding

        warn = Finding("agent_silent", Severity.warning, "a", "dc01", "x")
        crit = Finding("certificate_expired", Severity.critical, "b", "dc01", "y")
        assert exit_code([warn]) == EXIT_WARNING
        assert exit_code([warn, crit]) == EXIT_CRITICAL
        assert exit_code([crit, warn]) == EXIT_CRITICAL

    def test_the_codes_follow_the_convention(self) -> None:
        """0/1/2 wie bei Nagios. Der Sinn eines Exit-Codes ist, dass ihn
        etwas anderes liest — eine eigene Nummerierung wäre eine, die jede
        Überwachung erst übersetzen muss."""
        assert (EXIT_OK, EXIT_WARNING, EXIT_CRITICAL) == (0, 1, 2)


class TestTheEndpoint:
    def test_it_reports_findings_and_the_worst(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        import asyncio

        async def _seed() -> None:
            engine = create_async_engine(cockpit_schema, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                            "isolation_mode, dsn_ref, schema_name, db_role) VALUES "
                            "(gen_random_uuid(), 'lueckenhaft', 'Lueckenhaft', "
                            "'lueckenhaft.test', 'active', 'school', 'schema', 'l', 't_l', 'r_l')"
                        )
                    )
            finally:
                await engine.dispose()

        asyncio.run(_seed())
        response = console_client.get("/api/fleet/findings")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["worst"] == EXIT_WARNING
        assert any(f["kind"] == "tenant_without_agent" for f in body["findings"])

    def test_an_empty_console_reports_nothing(self, console_client: TestClient) -> None:
        body = console_client.get("/api/fleet/findings").json()
        assert body == {"findings": [], "worst": EXIT_OK}
