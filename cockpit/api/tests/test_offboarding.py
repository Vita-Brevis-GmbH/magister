"""Offboarding mit Fristen (ADR-0016 D8).

Geprüft werden die **Reihenfolgeschranken**, denn die sind der Inhalt: jede
verhindert einen Schaden, den man nicht zurücknehmen kann. Die
Abnahmekriterien dazu:

* Vor dem Löschen liegt ein zugestellter Export vor — das Recht des Kunden auf
  Herausgabe seiner Daten endet nicht mit der Kündigung.
* Vor Ablauf der Karenzzeit wird nichts gelöscht.
* Löschen verlangt zwei verschiedene Personen.
* „Vollständig gelöscht" wird erst gemeldet, wenn auch die Aufbewahrungsfrist
  der Sicherungen abgelaufen ist — vorher wäre es unwahr.

Der Löschschritt läuft gegen echtes Postgres: dass Schema **und** Rolle danach
wirklich weg sind, kann nur die Datenbank sagen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.models import ExportState, OffboardingState, TenantStatus
from cockpit_api.services.offboarding import ABORTABLE, STARTABLE

# Bewusst kein ``pytest.mark.asyncio``: alles hier läuft über ``TestClient``,
# also synchron. Wo eine Prüfung direkt an die Datenbank muss, öffnet sie ihre
# eigene Ereignisschleife (``asyncio.run``) — eine Fixture-Schleife und die des
# TestClient sind nicht dieselbe, und eine Engine aus der einen bringt in der
# anderen "attached to a different loop" mit.

SLUG = "abgang"


def _create(client: TestClient, slug: str = SLUG) -> dict[str, object]:
    resp = client.post(
        "/api/tenants",
        json={"slug": slug, "name": "Abgangsstadt", "hostname": f"{slug}.magister.test"},
    )
    assert resp.status_code in (201, 202), resp.text
    body: dict[str, object] = resp.json()
    return body


def _tenant_id(body: dict[str, object]) -> str:
    tenant: dict[str, object] = body["tenant"]  # type: ignore[assignment]
    return str(tenant["id"])


def _start(client: TestClient, tenant_id: str, **over: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "reason": "Kündigung per 31.12., Ticket VB-4711",
        "requested_by": "matthias",
        "grace_days": 30,
    }
    payload.update(over)
    resp = client.post(f"/api/tenants/{tenant_id}/offboarding", json=payload)
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


class TestPureLogic:
    """Braucht keine Datenbank."""

    def test_offboarding_starts_only_from_a_settled_state(self) -> None:
        """Nicht aus ``provisioning``: dort ist noch nichts fertig angelegt."""
        assert TenantStatus.active in STARTABLE
        assert TenantStatus.suspended in STARTABLE
        assert TenantStatus.provisioning not in STARTABLE
        assert TenantStatus.offboarding not in STARTABLE

    def test_only_states_before_deletion_can_be_aborted(self) -> None:
        """Ein Zustand, der einen Rückweg verspricht, den es nicht gibt, wäre eine Lüge."""
        assert set(ABORTABLE) == {OffboardingState.requested, OffboardingState.export_ready}
        for gone in (
            OffboardingState.dropped,
            OffboardingState.shredded,
            OffboardingState.purged,
        ):
            assert gone not in ABORTABLE


@pytest.mark.usefixtures("cockpit_schema")
class TestTheOrder:
    def test_starting_stops_serving_the_tenant(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        """``offboarding`` heisst in der Datenebene 503 (ADR-0013 D3).

        In einem Übergang, in dem Daten wandern, liest oder schreibt eine
        Anfrage einen halben Zustand.
        """
        tenant_id = _tenant_id(_create(db_client))
        row = _start(db_client, tenant_id)
        assert row["state"] == "requested"
        assert row["grace_until"] > row["requested_at"]
        after = db_client.get(f"/api/tenants/{tenant_id}").json()["tenant"]
        assert after["status"] == "offboarding"

    def test_offboarding_needs_a_named_reason(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        tenant_id = _tenant_id(_create(db_client, "grundlos"))
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding",
            json={"reason": "", "requested_by": "matthias"},
        )
        assert resp.status_code == 422, resp.text

    def test_nothing_is_dropped_without_a_delivered_export(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        """Die wichtigste Schranke.

        Die andere Reihenfolge wäre der Fall, in dem ein Kunde nach dem
        Anbieterwechsel nach seinen Daten fragt und wir sie nicht mehr haben.
        """
        tenant_id = _tenant_id(_create(db_client, "ohneexp"))
        _start(db_client, tenant_id, grace_days=0)
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "rolf"},
        )
        assert resp.status_code == 409, resp.text
        assert "Export" in resp.json()["detail"]

    def test_a_failed_export_does_not_lift_the_lock(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        """Sonst hätte der Kunde nichts in der Hand und wir hätten gelöscht."""
        tenant_id = _tenant_id(_create(db_client, "kaputtexp"))
        _start(db_client, tenant_id, grace_days=0)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.failed)
        resp = db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}")
        assert resp.status_code == 409, resp.text
        assert "fertiger" in resp.json()["detail"]

    def test_the_grace_period_holds(self, db_client: TestClient, cockpit_schema: str) -> None:
        """30 Tage sind da, damit ein Nachtrag noch möglich ist."""
        tenant_id = _tenant_id(_create(db_client, "karenz"))
        _start(db_client, tenant_id, grace_days=30)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.ready)
        assert (
            db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}").status_code
            == 200
        )
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "rolf"},
        )
        assert resp.status_code == 409, resp.text
        assert "Karenzzeit" in resp.json()["detail"]

    def test_one_person_cannot_drop_alone(self, db_client: TestClient, cockpit_schema: str) -> None:
        """Ein DROP SCHEMA auf ein Kundenschema ist die unwiderruflichste Operation."""
        tenant_id = _tenant_id(_create(db_client, "alleine"))
        _start(db_client, tenant_id, grace_days=0)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.ready)
        db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}")
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "Matthias"},
        )
        assert resp.status_code == 409, resp.text
        assert "verschieden" in resp.json()["detail"]

    def test_the_key_cannot_be_destroyed_before_the_drop(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        """Sonst wäre der Kunde online und könnte nichts mehr schreiben."""
        tenant_id = _tenant_id(_create(db_client, "frueh"))
        _start(db_client, tenant_id, grace_days=0)
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/key-destroyed",
            json={"confirmed_by": "matthias"},
        )
        assert resp.status_code == 409, resp.text

    def test_purged_is_not_reported_before_the_retention_elapsed(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        """„Vollständig gelöscht" vor Fristablauf wäre eine unwahre Zusage."""
        tenant_id = _tenant_id(_create(db_client, "zufrueh"))
        _start(db_client, tenant_id, grace_days=0)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.ready)
        db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}")
        dropped = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "rolf"},
        )
        assert dropped.status_code == 200, dropped.text
        shred = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/key-destroyed",
            json={"confirmed_by": "matthias"},
        )
        assert shred.status_code == 200, shred.text
        resp = db_client.post(f"/api/tenants/{tenant_id}/offboarding/purged")
        assert resp.status_code == 409, resp.text
        assert "Aufbewahrungsfrist" in resp.json()["detail"]


@pytest.mark.usefixtures("cockpit_schema")
class TestTheDropIsReal:
    def test_schema_and_role_are_gone_and_verified(
        self, db_client: TestClient, magister_admin_dsn: str, cockpit_schema: str
    ) -> None:
        """Der Dienst prüft nach. Ein Vermerk „gelöscht" ohne Nachprüfung wäre wertlos."""
        import asyncio

        tenant_id = _tenant_id(_create(db_client, "wegdamit"))
        _start(db_client, tenant_id, grace_days=0)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.ready)
        db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}")

        async def present() -> tuple[bool, bool]:
            engine = create_async_engine(magister_admin_dsn, poolclass=NullPool)
            try:
                async with engine.connect() as conn:
                    schema = (
                        await conn.execute(
                            text(
                                "SELECT 1 FROM information_schema.schemata "
                                "WHERE schema_name = 't_wegdamit'"
                            )
                        )
                    ).scalar()
                    role = (
                        await conn.execute(
                            text("SELECT 1 FROM pg_roles WHERE rolname = 'r_wegdamit'")
                        )
                    ).scalar()
                    return bool(schema), bool(role)
            finally:
                await engine.dispose()

        assert asyncio.run(present()) == (True, True), "die Bereitstellung ist nicht gelaufen"
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "rolf"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "dropped"
        assert body["dropped_by"] == "matthias"
        assert body["approved_by"] == "rolf"
        assert asyncio.run(present()) == (False, False)

    def test_the_key_id_is_kept_for_the_record(
        self, db_client: TestClient, magister_admin_dsn: str, cockpit_schema: str
    ) -> None:
        """Der Nachweis, *welcher* Schlüssel vernichtet wurde, soll bleiben."""
        created = _create(db_client, "welcher")
        tenant_id = _tenant_id(created)
        tenant = db_client.get(f"/api/tenants/{tenant_id}").json()["tenant"]
        assert tenant["audit_key_id"], "die Bereitstellung hat keine Schlüssel-Id gesetzt"

        _start(db_client, tenant_id, grace_days=0)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.ready)
        db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}")
        body = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "rolf"},
        ).json()
        assert body["key_id"] == tenant["audit_key_id"]

    def test_after_the_drop_there_is_no_way_back(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        tenant_id = _tenant_id(_create(db_client, "endgueltig"))
        _start(db_client, tenant_id, grace_days=0)
        export_id = _insert_export(cockpit_schema, tenant_id, ExportState.ready)
        db_client.post(f"/api/tenants/{tenant_id}/offboarding/export/{export_id}")
        db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/drop",
            json={"dropped_by": "matthias", "approved_by": "rolf"},
        )
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/abort",
            json={"reason": "Kunde hat es sich anders überlegt"},
        )
        assert resp.status_code == 409, resp.text


@pytest.mark.usefixtures("cockpit_schema")
class TestAbort:
    def test_a_withdrawal_before_deletion_restores_the_tenant(
        self, db_client: TestClient, cockpit_schema: str
    ) -> None:
        tenant_id = _tenant_id(_create(db_client, "zurueck"))
        _start(db_client, tenant_id)
        resp = db_client.post(
            f"/api/tenants/{tenant_id}/offboarding/abort",
            json={"reason": "Vertrag um ein Jahr verlängert"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "aborted"
        after = db_client.get(f"/api/tenants/{tenant_id}").json()["tenant"]
        assert after["status"] == "active"

    def test_a_withdrawal_needs_a_reason(self, db_client: TestClient, cockpit_schema: str) -> None:
        tenant_id = _tenant_id(_create(db_client, "obgrund"))
        _start(db_client, tenant_id)
        resp = db_client.post(f"/api/tenants/{tenant_id}/offboarding/abort", json={"reason": ""})
        assert resp.status_code == 422, resp.text


def _insert_export(console_dsn: str, tenant_id: str, state: ExportState) -> str:
    """Einen Export-Auftrag im gewünschten Zustand ablegen.

    Direkt in der Datenbank und nicht über den Endpunkt: der echte Export
    braucht ein migriertes Schema und ein Exportverzeichnis, und geprüft wird
    hier die *Reihenfolge* und nicht der Export.

    Der DSN kommt als Argument und nicht aus ``settings``: die Tests hängen
    die Sitzung auf die Testdatenbank um, ``settings.database_url`` zeigt
    weiter auf die Vorgabe — und dann schreibt der Helfer in eine Datenbank,
    die es nicht gibt.
    """
    import asyncio
    import uuid

    export_id = uuid.uuid4()

    async def insert() -> None:
        engine = create_async_engine(console_dsn, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO export_jobs (id, tenant_id, state, requested_by, "
                        "path, size_bytes, expires_at) VALUES "
                        "(:i, :t, :s, 'matthias', '/tmp/kein-echter-export.zip', 1, :e)"
                    ),
                    {
                        "i": export_id,
                        "t": uuid.UUID(tenant_id),
                        "s": state.value,
                        "e": datetime.now(UTC) + timedelta(days=7),
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    return str(export_id)
