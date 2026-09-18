"""Der Rückkanal: die Datenebene meldet ihren Schemastand (ADR-0021 D2).

Warum es diese Route gibt: `tenants.schema_version` trug bisher den Wert aus
`COCKPIT_EXPECTED_SCHEMA_VERSION` — also was die Konsole **erwartet** hat,
gesetzt beim Aktivieren. Genau diese Spalte fährt aber die Versions-Schranke
der Datenebene (ADR-0013 D7). Eine Erwartung, die nicht eingetroffen ist,
hält damit einen gesunden Kunden zurück oder lässt einen hinterherhängenden
durch.

Die Konsole kann die Angabe nicht selbst beschaffen: sie hat keinen
Datenbankzugang zum Kunden, und das bleibt so.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings


@pytest.fixture
def tenant_id(cockpit_schema: str) -> Iterator[str]:
    """Eine Kundenzeile, direkt gesetzt.

    Ohne Bereitstellung: die Route hat mit ihr nichts zu tun, und ein Test,
    der einen zweiten Cluster braucht, um eine Spalte zu prüfen, wird
    übersprungen und prüft dann nichts.
    """
    new_id = str(uuid.uuid4())

    async def _insert() -> None:
        engine = create_async_engine(cockpit_schema, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                        "isolation_mode, dsn_ref, schema_name, db_role, schema_version) "
                        "VALUES (:id, :slug, :name, :host, 'active', 'school', 'schema', "
                        ":ref, :schema, :role, :version)"
                    ),
                    {
                        "id": new_id,
                        "slug": "melder",
                        "name": "Melder",
                        "host": "melder.magister.test",
                        "ref": "melder",
                        "schema": "t_melder",
                        "role": "r_melder",
                        "version": "0040_erwartet",
                    },
                )
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(_insert())
    yield new_id


class TestTheReportIsAccepted:
    def test_the_reported_head_replaces_the_expectation(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        # Über die Liste und nicht über `GET /tenants/{id}`: das ist die
        # Sicht auf den BEREITSTELLUNGS-Auftrag und antwortet ohne einen
        # solchen mit 404. Dieser Kunde hat keinen — er ist hier direkt
        # gesetzt, weil die Route mit der Bereitstellung nichts zu tun hat.
        listing = console_client.get("/api/tenants").json()
        before = next(row for row in listing if row["id"] == tenant_id)
        assert before["schema_version"] == "0040_erwartet"
        assert before["schema_version_reported_at"] is None

        response = console_client.post(
            f"/api/tenants/{tenant_id}/schema-version",
            json={"head_revision": "0046_gemessen"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_version"] == "0046_gemessen"
        assert body["schema_version_reported_at"] is not None

    def test_the_same_report_twice_changes_nothing_but_the_timestamp(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        """Idempotent: ein Melder, der alle fünf Minuten meldet, ist normal."""
        first = console_client.post(
            f"/api/tenants/{tenant_id}/schema-version", json={"head_revision": "0046_x"}
        ).json()
        second = console_client.post(
            f"/api/tenants/{tenant_id}/schema-version", json={"head_revision": "0046_x"}
        ).json()
        assert first["schema_version"] == second["schema_version"] == "0046_x"
        assert second["schema_version_reported_at"] >= first["schema_version_reported_at"]

    def test_a_deviation_from_the_expectation_is_accepted_not_refused(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        """Eine Messung, die nicht zur Erwartung passt, ist eine Auskunft.

        Wer sie abwiese, hätte statt der Abweichung wieder nur die Erwartung
        in der Spalte — und damit genau das Problem, das die Route löst.
        """
        previous = settings.expected_schema_version
        settings.expected_schema_version = "0046_erwartet"
        try:
            response = console_client.post(
                f"/api/tenants/{tenant_id}/schema-version",
                json={"head_revision": "0041_hinterher"},
            )
        finally:
            settings.expected_schema_version = previous
        assert response.status_code == 200
        assert response.json()["schema_version"] == "0041_hinterher"


class TestRefusals:
    def test_an_unknown_tenant_is_404(self, console_client: TestClient) -> None:
        response = console_client.post(
            f"/api/tenants/{uuid.uuid4()}/schema-version",
            json={"head_revision": "0046_x"},
        )
        assert response.status_code == 404

    def test_an_extra_field_is_refused(self, console_client: TestClient, tenant_id: str) -> None:
        """Kein stiller Nicht-Effekt.

        Ein erweiterter Melder soll einen Fehler bekommen und nicht glauben,
        sein neues Feld sei angekommen — dieselbe Überlegung wie beim
        entfernten `actor` (ADR-0020 D3).
        """
        response = console_client.post(
            f"/api/tenants/{tenant_id}/schema-version",
            json={"head_revision": "0046_x", "schema_name": "t_fremd"},
        )
        assert response.status_code == 422

    def test_an_empty_revision_is_refused(self, console_client: TestClient, tenant_id: str) -> None:
        response = console_client.post(
            f"/api/tenants/{tenant_id}/schema-version", json={"head_revision": ""}
        )
        assert response.status_code == 422

    def test_without_the_management_marker_it_is_404(self, tenant_id: str) -> None:
        """Der Rückkanal liegt hinter demselben Riegel wie alles andere.

        404 und nicht 403: eine Sonde am öffentlichen Ursprung soll nicht
        erfahren, dass dort eine Konsole steht (ADR-0015 D1).
        """
        from cockpit_api.main import app

        with TestClient(app) as bare:
            response = bare.post(
                f"/api/tenants/{tenant_id}/schema-version",
                json={"head_revision": "0046_x"},
                headers={"Authorization": f"Bearer {settings.bootstrap_token}"},
            )
        assert response.status_code == 404
