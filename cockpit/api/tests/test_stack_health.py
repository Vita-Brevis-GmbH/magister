"""Die tiefe Sonde der Konsole — was PRTG liest.

`/api/health` sagt „der Prozess lebt", und das muss so bleiben: eine flache
Sonde, die die Datenbank prüft, lässt einen Orchestrierer den Prozess neu
starten, weil die Datenbank hustet.

Hier steht die andere Hälfte: Datenbank, Bereitstellungen, Restlaufzeit der
Connector-CA und der schlimmste Flottenbefund — in einer Zahl nach derselben
Konvention wie `fleet_check` (ADR-0021 D6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings
from cockpit_api.models import (
    AgentStatus,
    ConnectorAgent,
    JobStatus,
    ProvisioningJob,
    Tenant,
    TenantStatus,
)
from cockpit_api.services.stack_health import CRITICAL, OK, WARNING, stack_health

NOW = datetime.now(UTC)


@pytest.fixture
def session_factory(cockpit_schema: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(cockpit_schema, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)


def _write_ca(path: str, *, days: int) -> None:
    """Ein echtes Zertifikat mit gewünschter Restlaufzeit.

    Kein vorgetäuschtes Objekt: die Prüfung liest eine **Datei**, und ob sie
    das kann, ist die halbe Zusage. Ein Mock hätte genau den Teil übersprungen,
    der im Betrieb schiefgeht (falscher Pfad, falsche Rechte, PEM kaputt).
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Magister Connector Test CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    with open(path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))


async def _tenant(session: AsyncSession, slug: str, *, status: TenantStatus) -> Tenant:
    tenant = Tenant(
        slug=slug,
        name=slug.title(),
        hostname=f"{slug}.mgmt.vitabrevis.test",
        status=status,
        dsn_ref=slug,
        schema_name=f"t_{slug}",
        db_role=f"r_{slug}",
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def _silent_agent(session: AsyncSession, tenant: Tenant) -> None:
    session.add(
        ConnectorAgent(
            tenant_id=tenant.id,
            name="dc01",
            status=AgentStatus.online,
            spki_sha256=uuid.uuid4().hex * 2,
            certificate_serial=uuid.uuid4().hex[:16],
            certificate_not_after=NOW + timedelta(days=200),
            api_key_hash="argon2-hash",
            result_hmac_key="hmac",
            agent_version="1.4.0",
            last_seen_at=NOW - timedelta(days=2),
        )
    )
    await session.flush()


@pytest.mark.asyncio
class TestTheStackProbe:
    async def test_a_quiet_platform_is_zero(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        ca = tmp_path / "connector-int.pem"
        _write_ca(str(ca), days=200)
        monkeypatch.setattr(settings, "connector_ca_cert", str(ca))
        async with session_factory() as session:
            health = await stack_health(session)
        assert health.status == OK
        assert health.state == "ok"
        names = {c.name for c in health.checks}
        assert names == {"database", "connector_ca", "fleet"}

    async def test_an_active_tenant_without_an_agent_is_a_warning(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        """Kein Agent heisst: bei diesem Kunden geht kein Passwort-Reset.

        Beim Schreiben dieses Tests aufgefallen — die erste Fassung erwartete
        hier 0 und war schlicht falsch: die Flotte meldet den Kunden ohne
        Agenten zu Recht, und die Sonde übernimmt den Befund.
        """
        ca = tmp_path / "connector-int.pem"
        _write_ca(str(ca), days=200)
        monkeypatch.setattr(settings, "connector_ca_cert", str(ca))
        async with session_factory() as session:
            await _tenant(session, "ohneagent", status=TenantStatus.active)
            await session.commit()
            health = await stack_health(session)
        assert health.status == WARNING
        fleet = next(c for c in health.checks if c.name == "fleet")
        assert fleet.status == WARNING

    async def test_a_tenant_in_provisioning_is_a_warning(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        """Während einer Einrichtung normal, nach einer Stunde ein Befund.

        Die Unterscheidung trifft ein Mensch — deshalb Warnung und nicht
        kritisch. Eine Sonde, die jede Einrichtung rot färbt, wird abgestellt.
        """
        ca = tmp_path / "connector-int.pem"
        _write_ca(str(ca), days=200)
        monkeypatch.setattr(settings, "connector_ca_cert", str(ca))
        async with session_factory() as session:
            await _tenant(session, "halbfertig", status=TenantStatus.provisioning)
            await session.commit()
            health = await stack_health(session)
        assert health.status == WARNING
        assert any(c.name == "provisioning" and c.status == WARNING for c in health.checks)

    async def test_a_failed_provisioning_job_shows_up(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        ca = tmp_path / "connector-int.pem"
        _write_ca(str(ca), days=200)
        monkeypatch.setattr(settings, "connector_ca_cert", str(ca))
        async with session_factory() as session:
            tenant = await _tenant(session, "abbruch", status=TenantStatus.active)
            session.add(
                ProvisioningJob(tenant_id=tenant.id, status=JobStatus.failed, steps=[], attempts=1)
            )
            await session.commit()
            health = await stack_health(session)
        assert any(c.name == "provisioning_jobs" for c in health.checks)
        assert health.status == WARNING

    async def test_an_expiring_connector_ca_is_critical(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        """Läuft sie ab, kommt kein Agent mehr herein — und keiner kann sich erneuern."""
        ca = tmp_path / "connector-int.pem"
        _write_ca(str(ca), days=3)
        monkeypatch.setattr(settings, "connector_ca_cert", str(ca))
        async with session_factory() as session:
            await _tenant(session, "knapp", status=TenantStatus.active)
            await session.commit()
            health = await stack_health(session)
        cert = next(c for c in health.checks if c.name == "connector_ca")
        assert cert.status == CRITICAL
        assert health.status == CRITICAL

    async def test_a_missing_ca_file_is_named_not_swallowed(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "connector_ca_cert", str(tmp_path / "gibtsnicht.pem"))
        async with session_factory() as session:
            await _tenant(session, "ohnecert", status=TenantStatus.active)
            await session.commit()
            health = await stack_health(session)
        cert = next(c for c in health.checks if c.name == "connector_ca")
        assert cert.status == CRITICAL
        assert "nicht lesbar" in cert.detail

    async def test_the_fleet_verdict_is_taken_not_recomputed(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path, monkeypatch
    ) -> None:
        """Zwei Stellen, die denselben Schweregrad rechnen, rechnen ihn verschieden."""
        ca = tmp_path / "connector-int.pem"
        _write_ca(str(ca), days=200)
        monkeypatch.setattr(settings, "connector_ca_cert", str(ca))
        async with session_factory() as session:
            tenant = await _tenant(session, "still", status=TenantStatus.active)
            await _silent_agent(session, tenant)
            await session.commit()
            health = await stack_health(session)
        fleet = next(c for c in health.checks if c.name == "fleet")
        assert fleet.status == CRITICAL
        assert "kritisch" in fleet.detail


class TestTheRoute:
    def test_the_flat_probe_stays_flat(self, client: TestClient) -> None:
        """Sie darf nichts anfassen, was ausfallen kann — sonst startet der
        Orchestrierer den Prozess neu, weil die Datenbank hustet."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_the_deep_probe_answers_with_a_number(self, db_client: TestClient) -> None:
        resp = db_client.get("/api/health/stack")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in (0, 1, 2)
        assert body["state"] in ("ok", "warning", "critical")
        assert {c["name"] for c in body["checks"]} >= {"database"}
