"""Lastgrenzen an der Mandantenrolle (ADR-0021 D3).

Der Punkt dieser Datei: die Grenzen stehen nicht in einer Spalte, **sie
stehen in Postgres**. Eine Zeile in der Konsole, die eine Grenze behauptet,
die im Cluster nicht gilt, wäre schlechter als keine Angabe — deshalb prüfen
die Tests hier `pg_roles` und `pg_db_role_setting` und nicht das JSON der
Antwort.

Warum an der Rolle und nicht im Anfragepfad: eine Rollen-Einstellung gilt auch
für den Codepfad, den jemand vergisst, für das CLI, für den Abgleich und für
eine Wiederherstellung. Was an der Rolle hängt, kann die Anwendung nicht aus
Versehen weglassen.

Die Verbindungsgrenze ist die eigentliche Zusage: ohne sie nimmt der erste
Kunde, der viele Verbindungen aufbaut, den anderen ihre weg, bis
`max_connections` erschöpft ist und **alle** ausfallen.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


async def _role_settings(admin_dsn: str, role: str) -> tuple[int, list[str]]:
    """Verbindungsgrenze und gesetzte Parameter dieser Rolle."""
    engine = create_async_engine(admin_dsn, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT r.rolconnlimit, s.setconfig "
                        "FROM pg_roles r "
                        "LEFT JOIN pg_db_role_setting s ON s.setrole = r.oid "
                        "WHERE r.rolname = :role"
                    ),
                    {"role": role},
                )
            ).one_or_none()
    finally:
        await engine.dispose()
    assert row is not None, f"Rolle {role} existiert nicht"
    return int(row[0]), list(row[1] or [])


def _provision(client: TestClient, slug: str) -> dict[str, Any]:
    response = client.post(
        "/api/tenants",
        json={
            "slug": slug,
            "name": slug.title(),
            "hostname": f"{slug}.magister.test",
        },
    )
    assert response.status_code in (201, 202), response.text
    return response.json()


class TestProvisioningSetsThem:
    @pytest.mark.asyncio
    async def test_a_fresh_role_carries_all_three_limits(
        self, db_client: TestClient, magister_admin_dsn: str
    ) -> None:
        slug = f"grenz{uuid.uuid4().hex[:8]}"
        result = _provision(db_client, slug)
        assert result["tenant"]["connection_limit"] == 40

        conn_limit, config = await _role_settings(magister_admin_dsn, f"r_{slug}")
        assert conn_limit == 40
        assert "statement_timeout=30000ms" in config
        assert "idle_in_transaction_session_timeout=60000ms" in config

    @pytest.mark.asyncio
    async def test_the_step_says_what_it_set(self, db_client: TestClient) -> None:
        """Sonst ist eine Grenze etwas, das man nur in Postgres nachsieht."""
        slug = f"grenz{uuid.uuid4().hex[:8]}"
        result = _provision(db_client, slug)
        step = next(s for s in result["job"]["steps"] if s["step"] == "create_role")
        assert "Grenzen gesetzt" in step["detail"]
        assert "statement_timeout=30000ms" in step["detail"]


class TestChangingThem:
    @pytest.mark.asyncio
    async def test_a_change_reaches_postgres(
        self, db_client: TestClient, magister_admin_dsn: str
    ) -> None:
        slug = f"grenz{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]

        response = db_client.put(
            f"/api/tenants/{tenant_id}/limits",
            json={
                "statement_timeout_ms": 5_000,
                "idle_in_transaction_ms": 10_000,
                "connection_limit": 12,
                "reason": "Auswertung des Kunden bricht ab",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["statement_timeout_ms"] == 5_000

        conn_limit, config = await _role_settings(magister_admin_dsn, f"r_{slug}")
        assert conn_limit == 12
        assert "statement_timeout=5000ms" in config
        assert "idle_in_transaction_session_timeout=10000ms" in config

    def test_a_reason_is_required(self, db_client: TestClient) -> None:
        """Eine Grenze zu heben ist eine Entscheidung und kein Handgriff."""
        slug = f"grenz{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]
        response = db_client.put(
            f"/api/tenants/{tenant_id}/limits",
            json={
                "statement_timeout_ms": 5_000,
                "idle_in_transaction_ms": 10_000,
                "connection_limit": 12,
            },
        )
        assert response.status_code == 422

    def test_there_is_no_unlimited(self, db_client: TestClient) -> None:
        """`-1` wäre der Zustand, den ADR-0021 D3 beendet."""
        slug = f"grenz{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]
        for payload in (
            {"connection_limit": -1},
            {"connection_limit": 0},
            # Unter zehn liegt unter Pool plus Overflow eines einzigen
            # Prozesses — das sperrt den Kunden im Normalbetrieb aus.
            {"connection_limit": 5},
            # Eine Sekunde ist die Untergrenze; darunter bricht alles ab.
            {"statement_timeout_ms": 10},
        ):
            body = {
                "statement_timeout_ms": 5_000,
                "idle_in_transaction_ms": 10_000,
                "connection_limit": 12,
                "reason": "Versuch",
                **payload,
            }
            response = db_client.put(f"/api/tenants/{tenant_id}/limits", json=body)
            assert response.status_code == 422, (payload, response.text)

    def test_an_extra_field_is_refused(self, db_client: TestClient) -> None:
        slug = f"grenz{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]
        response = db_client.put(
            f"/api/tenants/{tenant_id}/limits",
            json={
                "statement_timeout_ms": 5_000,
                "idle_in_transaction_ms": 10_000,
                "connection_limit": 12,
                "reason": "Versuch",
                "db_role": "r_fremd",
            },
        )
        assert response.status_code == 422

    def test_an_unknown_tenant_is_404(self, db_client: TestClient) -> None:
        response = db_client.put(
            f"/api/tenants/{uuid.uuid4()}/limits",
            json={
                "statement_timeout_ms": 5_000,
                "idle_in_transaction_ms": 10_000,
                "connection_limit": 12,
                "reason": "Versuch",
            },
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_a_failed_alter_role_changes_nothing(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        """Beides oder keines.

        `console_client` hat keinen Verwaltungszugang in den Magister-Cluster
        (`COCKPIT_TENANT_ADMIN_DSN` ist leer). Dann muss die Antwort ein 503
        sein **und** die Spalte unverändert bleiben — eine Zeile, die eine
        Grenze behauptet, die in Postgres nicht gilt, ist schlechter als keine
        Angabe.
        """
        tenant_id = str(uuid.uuid4())
        engine = create_async_engine(cockpit_schema, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                        "isolation_mode, dsn_ref, schema_name, db_role) VALUES "
                        "(:id, 'ohnecluster', 'Ohne Cluster', 'ohnecluster.test', 'active', "
                        "'school', 'schema', 'ohnecluster', 't_ohnecluster', 'r_ohnecluster')"
                    ),
                    {"id": tenant_id},
                )
        finally:
            await engine.dispose()

        response = console_client.put(
            f"/api/tenants/{tenant_id}/limits",
            json={
                "statement_timeout_ms": 5_000,
                "idle_in_transaction_ms": 10_000,
                "connection_limit": 12,
                "reason": "Versuch ohne Cluster",
            },
        )
        assert response.status_code == 503, response.text

        listing = console_client.get("/api/tenants").json()
        row = next(r for r in listing if r["id"] == tenant_id)
        assert row["statement_timeout_ms"] == 30_000, "Spalte wurde trotz Fehler geändert"


class TestRelocating:
    """ADR-0021 D5: der Umzug ist ein Runbook, und dies ist sein einziger Knopf."""

    def test_an_active_tenant_cannot_be_relocated(self, db_client: TestClient) -> None:
        """Sonst zeigte die Registry auf eine Datenbank, in der die Daten
        noch nicht sind — und die Datenebene bediente aus einem halb
        gefüllten Schema."""
        slug = f"umzug{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]
        response = db_client.post(
            f"/api/tenants/{tenant_id}/relocate",
            json={
                "dsn_ref": "zielcluster",
                "isolation_mode": "cluster",
                "reason": "Kunde wird gross",
            },
        )
        assert response.status_code == 409
        assert "gesperrt" in response.json()["detail"]

    def test_a_suspended_tenant_moves_and_loses_its_reported_stand(
        self, db_client: TestClient
    ) -> None:
        """Der gemeldete Stand war eine Messung an der ALTEN Ablage.

        Ihn stehen zu lassen wäre die Behauptung, das Ziel sei schon geprüft.
        Die nächste Meldung der Datenebene ist der Beleg, dass der Umzug
        angekommen ist.
        """
        slug = f"umzug{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]
        # Stand melden, damit es etwas zu verlieren gibt.
        db_client.post(f"/api/tenants/{tenant_id}/schema-version", json={"head_revision": "0046_x"})
        db_client.post(f"/api/tenants/{tenant_id}/suspend", json={"reason": "Umzug heute Nacht"})

        response = db_client.post(
            f"/api/tenants/{tenant_id}/relocate",
            json={
                "dsn_ref": "zielcluster",
                "isolation_mode": "cluster",
                "reason": "Kunde bekommt eigenen Cluster",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["dsn_ref"] == "zielcluster"
        assert body["isolation_mode"] == "cluster"
        assert body["schema_version"] is None
        assert body["schema_version_reported_at"] is None

    def test_an_unchanged_target_is_refused(self, db_client: TestClient) -> None:
        """Ein Umzug, der nichts ändert, ist ein Protokolleintrag ohne Vorgang."""
        slug = f"umzug{uuid.uuid4().hex[:8]}"
        result = _provision(db_client, slug)
        tenant_id = result["tenant"]["id"]
        current = result["tenant"]["dsn_ref"]
        db_client.post(f"/api/tenants/{tenant_id}/suspend", json={"reason": "Umzug"})
        response = db_client.post(
            f"/api/tenants/{tenant_id}/relocate",
            json={"dsn_ref": current, "isolation_mode": "schema", "reason": "nichts"},
        )
        assert response.status_code == 409

    def test_a_dsn_is_not_a_ref(self, db_client: TestClient) -> None:
        """Ein DSN gehört nicht in die Konsole (ADR-0013 D2).

        Das Muster ist die Grenze: was hier durchkäme, würde zum Namen einer
        Umgebungsvariablen — und ein Verbindungsstring als Variablenname ist
        ein Verbindungsstring in der Konsolen-Datenbank.
        """
        slug = f"umzug{uuid.uuid4().hex[:8]}"
        tenant_id = _provision(db_client, slug)["tenant"]["id"]
        db_client.post(f"/api/tenants/{tenant_id}/suspend", json={"reason": "Umzug"})
        response = db_client.post(
            f"/api/tenants/{tenant_id}/relocate",
            json={
                "dsn_ref": "postgresql://magister:geheim@db:5432/magister",
                "isolation_mode": "cluster",
                "reason": "Versuch",
            },
        )
        assert response.status_code == 422
