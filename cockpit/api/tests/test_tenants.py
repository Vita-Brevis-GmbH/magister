"""Bereitstellung: zwei Kunden, echte Trennung, nie halb angelegt.

Die Abnahmekriterien aus Phase 2 (ADR-0013 D2):

- Zwei Kunden auf einer Installation, gegenseitiger DB-Zugriff scheitert an
  Postgres — nicht an einem Filter in der Anwendung.
- Ein abgebrochener Auftrag lässt den Kunden auf ``provisioning`` und
  unerreichbar.

Die datenbankgestützten Tests brauchen ``COCKPIT_TEST_DATABASE_URL`` und
``COCKPIT_TEST_TENANT_ADMIN_DSN`` und werden sonst übersprungen.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from cockpit_api.config import settings
from cockpit_api.models import STEP_ORDER, ProvisioningStep
from cockpit_api.models.tenant import SLUG_PATTERN
from cockpit_api.services.provisioning import (
    IDENTIFIER_PATTERN,
    SCRAM_ITERATIONS,
    ProvisioningError,
    _ident,
    new_role_password,
    scram_verifier,
)


class TestPureLogic:
    """Läuft ohne Postgres."""

    def test_the_step_order_is_explicit_and_complete(self) -> None:
        # Die Reihenfolge trägt Korrektheit: Rolle vor Schema (das Schema
        # gehört ihr), Schema vor Migration, aktiv erst zuletzt.
        assert STEP_ORDER == (
            ProvisioningStep.create_role,
            ProvisioningStep.create_schema,
            ProvisioningStep.migrate,
            ProvisioningStep.data_key,
            ProvisioningStep.activate,
        )
        assert set(STEP_ORDER) == set(ProvisioningStep)

    def test_the_slug_pattern_matches_the_data_plane(self) -> None:
        """Konsole und Datenebene müssen denselben Slug akzeptieren.

        Driftet das auseinander, legt die Konsole Kunden an, die die
        Datenebene beim Start ablehnt — und das fällt erst im Betrieb auf.
        """
        assert SLUG_PATTERN.pattern == r"^[a-z][a-z0-9_]{1,30}$"

    @pytest.mark.parametrize(
        "bad",
        ['t_a"; DROP SCHEMA t_b; --', "T_Alpha", "1alpha", "t-alpha", "", "a" * 64],
    )
    def test_a_bad_identifier_never_reaches_sql(self, bad: str) -> None:
        with pytest.raises(ProvisioningError, match="Bezeichner"):
            _ident(bad, field="schema_name")

    def test_a_good_identifier_is_quoted(self) -> None:
        assert _ident("t_alpha", field="schema_name") == '"t_alpha"'

    def test_the_identifier_pattern_rejects_what_the_slug_allows_plus_prefix(self) -> None:
        # t_ plus 31 Zeichen Slug bleibt unter der Postgres-Grenze von 63.
        assert IDENTIFIER_PATTERN.match("t_" + "a" * 31)

    def test_the_role_password_is_long_and_random(self) -> None:
        a, b = new_role_password(), new_role_password()
        assert a != b
        assert len(a) >= 40
        # URL-safe base64: nichts, was in einem DSN zitiert werden müsste.
        assert re.fullmatch(r"[A-Za-z0-9_-]+", a)


class TestScramVerifier:
    """``CREATE ROLE ... PASSWORD`` nimmt keine Bind-Parameter.

    Das Passwort müsste also als Literal ins SQL — und stünde damit im
    Postgres-Log, sobald ``log_statement = ddl`` gesetzt ist. Deshalb geht ein
    vorberechneter Verifier über die Leitung. Dass die Ableitung stimmt, zeigt
    erst ``TestProvisioning``: dort wird mit dem Klartextpasswort tatsächlich
    eine Verbindung aufgebaut.
    """

    def test_the_format_matches_what_postgres_expects(self) -> None:
        verifier = scram_verifier("abcDEF123-_", salt=b"0123456789abcdef")
        assert verifier.startswith(f"SCRAM-SHA-256${SCRAM_ITERATIONS}:")
        head, _, tail = verifier.partition("$")
        assert head == "SCRAM-SHA-256"
        iterations_salt, _, keys = tail.partition("$")
        assert iterations_salt.startswith(f"{SCRAM_ITERATIONS}:")
        stored, _, server = keys.partition(":")
        # Beide Schlüssel sind 32 Byte SHA-256 → 44 Zeichen base64.
        assert len(stored) == len(server) == 44

    def test_it_is_deterministic_for_a_given_salt(self) -> None:
        a = scram_verifier("abcDEF123", salt=b"x" * 16)
        b = scram_verifier("abcDEF123", salt=b"x" * 16)
        assert a == b
        assert scram_verifier("abcDEF124", salt=b"x" * 16) != a

    def test_a_random_salt_is_used_by_default(self) -> None:
        assert scram_verifier("abcDEF123") != scram_verifier("abcDEF123")

    def test_it_refuses_a_password_it_cannot_saslprep(self) -> None:
        # Für das eigene Alphabet ist SASLprep die Identität; für ein fremdes
        # Passwort nicht, und dann wäre der Verifier eventuell falsch.
        with pytest.raises(ProvisioningError, match="Alphabet"):
            scram_verifier("Pässwort mit Umlaut")

    def test_the_generated_password_never_needs_escaping(self) -> None:
        # Der Verifier geht als Literal ins SQL. Dass das Passwort selbst nie
        # dorthin kommt, ist die eine Absicherung; dass es auch harmlos wäre,
        # die zweite.
        for _ in range(50):
            assert scram_verifier(new_role_password())


class TestValidation:
    """Braucht keine Datenbank: die Prüfung greift vor jedem DB-Zugriff."""

    def test_a_bad_slug_is_refused_with_422(self, authed_client: TestClient) -> None:
        resp = authed_client.post(
            "/api/tenants",
            json={"slug": "Nicht Erlaubt", "name": "X", "hostname": "x.magister.ch"},
        )
        assert resp.status_code == 422

    def test_suspending_needs_a_reason(self, authed_client: TestClient) -> None:
        # Sperren ohne Begründung ist der Anfang von Willkür — der Grund ist
        # für den Kunden sichtbar und deshalb Pflichtfeld.
        resp = authed_client.post(
            "/api/tenants/00000000-0000-0000-0000-000000000000/suspend", json={"reason": ""}
        )
        assert resp.status_code == 422


def _payload(slug: str) -> dict[str, str]:
    return {
        "slug": slug,
        "name": f"Gemeinde {slug}",
        "hostname": f"{slug}.magister.test",
    }


@pytest.mark.usefixtures("cockpit_schema")
class TestProvisioning:
    """Gegen echtes Postgres: hier entscheidet die Datenbank, nicht der Test."""

    def test_two_tenants_cannot_reach_each_other(
        self, db_client: TestClient, magister_admin_dsn: str
    ) -> None:
        """Das Abnahmekriterium. Ohne Alembic — Phase 1 hat den Teil belegt.

        Es werden nur Rolle und Schema bereitgestellt (die ersten zwei
        Schritte); der Rest scheitert an fehlendem Alembic-Verzeichnis, was
        hier nichts stört: die Trennung entsteht in Schritt 2.
        """
        first = db_client.post("/api/tenants", json=_payload("iso_a"))
        second = db_client.post("/api/tenants", json=_payload("iso_b"))
        assert first.status_code in (201, 202), first.text
        assert second.status_code in (201, 202), second.text
        pw_a = first.json()["role_password"]
        assert pw_a, "das Rollenpasswort kommt genau einmal zurück"

        import asyncio

        async def probe() -> tuple[bool, str]:
            dsn = str(make_url(magister_admin_dsn).set(username="r_iso_a", password=pw_a))
            engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
            try:
                async with engine.connect() as conn:
                    await conn.execute(text('SET LOCAL search_path = "t_iso_a"'))
                    own = (await conn.execute(text("SELECT current_user"))).scalar()
                    try:
                        # Der Angriff: qualifizierter Griff ins Nachbarschema.
                        await conn.execute(text("CREATE TABLE t_iso_b.eingedrungen (x int)"))
                        return True, str(own)
                    except Exception as exc:
                        return False, f"{own}: {type(exc).__name__} {str(exc)[:60]}"
            finally:
                await engine.dispose()

        breached, detail = asyncio.run(probe())
        assert not breached, f"Kunde A kam in das Schema von Kunde B: {detail}"
        assert "r_iso_a" in detail

    def test_the_returned_password_actually_works(
        self, db_client: TestClient, magister_admin_dsn: str
    ) -> None:
        """Der Beweis, dass die SCRAM-Ableitung stimmt.

        Die Konsole schickt einen Verifier an Postgres und gibt das
        Klartextpasswort an den Aufrufer. Rechnet sie falsch, passt beides
        nicht zusammen — und das merkt man erst, wenn sich jemand anmelden
        will. Also melden wir uns an.
        """
        created = db_client.post("/api/tenants", json=_payload("anmeldbar"))
        password = created.json()["role_password"]
        assert password

        import asyncio

        async def connect_as_tenant() -> str | None:
            dsn = str(make_url(magister_admin_dsn).set(username="r_anmeldbar", password=password))
            engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
            try:
                async with engine.connect() as conn:
                    return (await conn.execute(text("SELECT current_user"))).scalar()
            finally:
                await engine.dispose()

        assert asyncio.run(connect_as_tenant()) == "r_anmeldbar"

    def test_the_console_never_stores_the_role_password(self, db_client: TestClient) -> None:
        created = db_client.post("/api/tenants", json=_payload("nopw"))
        password = created.json()["role_password"]
        assert password

        tenant_id = created.json()["tenant"]["id"]
        again = db_client.get(f"/api/tenants/{tenant_id}")
        assert again.status_code == 200
        # Nicht mehr abrufbar — und auch nirgends im Auftragsprotokoll.
        assert again.json()["role_password"] is None
        assert password not in again.text

    def test_a_failed_job_leaves_the_tenant_provisioning(self, db_client: TestClient) -> None:
        """Das zweite Abnahmekriterium.

        Der Migrationsschritt scheitert hier, weil kein Alembic-Verzeichnis
        konfiguriert ist. Der Kunde muss danach auf ``provisioning`` stehen —
        nicht erreichbar ist besser als halb bedient.
        """
        settings.magister_api_dir = ""
        created = db_client.post("/api/tenants", json=_payload("halb"))
        assert created.status_code == 202, "kein 201: der Auftrag ist nicht durch"
        body = created.json()
        assert body["tenant"]["status"] == "provisioning"
        assert body["job"]["status"] == "failed"
        assert body["job"]["last_completed_step"] == "create_schema"
        assert body["next_step"] == "migrate"
        assert "COCKPIT_MAGISTER_API_DIR" in body["job"]["last_error"]
        # Die erledigten Schritte stehen mit Begründung im Protokoll.
        steps = {s["step"]: s["ok"] for s in body["job"]["steps"]}
        assert steps == {"create_role": True, "create_schema": True, "migrate": False}

    def test_a_suspended_tenant_cannot_be_suspended_while_provisioning(
        self, db_client: TestClient
    ) -> None:
        settings.magister_api_dir = ""
        created = db_client.post("/api/tenants", json=_payload("nochnicht"))
        tenant_id = created.json()["tenant"]["id"]
        resp = db_client.post(f"/api/tenants/{tenant_id}/suspend", json={"reason": "Test"})
        # Sperren eines halb bereitgestellten Kunden wäre sinnlos: er ist
        # ohnehin nicht erreichbar.
        assert resp.status_code == 409

    def test_a_duplicate_slug_is_a_conflict(self, db_client: TestClient) -> None:
        db_client.post("/api/tenants", json=_payload("zweimal"))
        again = db_client.post("/api/tenants", json=_payload("zweimal"))
        assert again.status_code == 409

    def test_the_registry_feed_carries_no_dsn(self, db_client: TestClient) -> None:
        """Ein Abruf der Registry gibt niemandem Datenbankzugang (ADR-0013 D4)."""
        db_client.post("/api/tenants", json=_payload("feed"))
        resp = db_client.get("/api/tenants/registry")
        assert resp.status_code == 200
        entry = next(e for e in resp.json() if e["slug"] == "feed")
        assert entry["dsn_ref"] == "tenant_feed"
        assert "dsn" not in entry
        assert "password" not in resp.text.lower()

    def test_the_registry_feed_includes_non_active_tenants(self, db_client: TestClient) -> None:
        # Die Datenebene muss sie kennen, um 503 statt 404 zu antworten:
        # "gibt es nicht" und "gerade nicht erreichbar" sind verschiedene
        # Auskünfte.
        settings.magister_api_dir = ""
        db_client.post("/api/tenants", json=_payload("wartend"))
        entry = next(
            e for e in db_client.get("/api/tenants/registry").json() if e["slug"] == "wartend"
        )
        assert entry["status"] == "provisioning"

    def test_a_full_provisioning_run_activates_and_migrates(
        self, db_client: TestClient, magister_admin_dsn: str
    ) -> None:
        """Der komplette Auftrag, inklusive Alembic — der langsame Test.

        Übersprungen ohne ``COCKPIT_TEST_MAGISTER_API_DIR``, weil er das
        Alembic-Verzeichnis der Datenebene braucht.
        """
        if not settings.magister_api_dir:
            pytest.skip("COCKPIT_TEST_MAGISTER_API_DIR nicht gesetzt")

        created = db_client.post("/api/tenants", json=_payload("ganz"))
        body = created.json()
        assert created.status_code == 201, body.get("job", {}).get("last_error")
        assert body["tenant"]["status"] == "active"
        assert body["job"]["status"] == "succeeded"
        assert body["next_step"] is None
        assert body["tenant"]["schema_version"] == settings.expected_schema_version
        # data_key ist noch nicht umgesetzt und sagt das ausdrücklich, statt
        # den Eindruck zu erwecken, jeder Kunde hätte schon einen eigenen.
        data_key = next(s for s in body["job"]["steps"] if s["step"] == "data_key")
        assert data_key["ok"] and "installationsweite" in data_key["detail"]

        import asyncio

        async def check_owner() -> tuple[int, str | None]:
            engine = create_async_engine(magister_admin_dsn)
            try:
                async with engine.connect() as conn:
                    count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM information_schema.tables "
                                "WHERE table_schema = 't_ganz'"
                            )
                        )
                    ).scalar_one()
                    owner = (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT tableowner FROM pg_tables "
                                "WHERE schemaname = 't_ganz'"
                            )
                        )
                    ).scalar()
                    return int(count), owner
            finally:
                await engine.dispose()

        table_count, owner = asyncio.run(check_owner())
        assert table_count > 20, "Alembic hat nicht in das Kundenschema migriert"
        # Der Fallstrick aus Phase 1: als Verwaltungsrolle migriert, gehören
        # die Tabellen ihr, und der Kunde bekommt "permission denied".
        assert owner == "r_ganz"

    def test_suspend_and_unsuspend_leave_the_data_alone(
        self, db_client: TestClient, magister_admin_dsn: str
    ) -> None:
        """Sperren ist eine Aussage über die Bedienung, nicht über den Bestand."""
        if not settings.magister_api_dir:
            pytest.skip("COCKPIT_TEST_MAGISTER_API_DIR nicht gesetzt")

        created = db_client.post("/api/tenants", json=_payload("sperrbar"))
        assert created.status_code == 201, created.text
        tenant_id = created.json()["tenant"]["id"]

        blocked = db_client.post(
            f"/api/tenants/{tenant_id}/suspend", json={"reason": "Rechnung offen, Ticket 4711"}
        )
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "suspended"
        assert blocked.json()["suspended_reason"] == "Rechnung offen, Ticket 4711"
        assert blocked.json()["suspended_at"] is not None

        import asyncio

        async def count_tables() -> int:
            engine = create_async_engine(magister_admin_dsn)
            try:
                async with engine.connect() as conn:
                    return int(
                        (
                            await conn.execute(
                                text(
                                    "SELECT count(*) FROM information_schema.tables "
                                    "WHERE table_schema = 't_sperrbar'"
                                )
                            )
                        ).scalar_one()
                    )
            finally:
                await engine.dispose()

        # Rolle, Schema und Daten bleiben stehen — sonst wäre Entsperren eine
        # Wiederherstellung.
        assert asyncio.run(count_tables()) > 20

        freed = db_client.post(f"/api/tenants/{tenant_id}/unsuspend")
        assert freed.status_code == 200
        assert freed.json()["status"] == "active"
        assert freed.json()["suspended_reason"] is None
        # Zweimal entsperren ist ein Konflikt, keine stille Wiederholung.
        assert db_client.post(f"/api/tenants/{tenant_id}/unsuspend").status_code == 409

    def test_resume_continues_from_the_failed_step(self, db_client: TestClient) -> None:
        """Wiederaufnehmen macht nicht von vorn, aber es scheitert auch nicht
        daran, dass Rolle und Schema schon existieren."""
        if not settings.magister_api_dir:
            pytest.skip("COCKPIT_TEST_MAGISTER_API_DIR nicht gesetzt")

        configured = settings.magister_api_dir
        settings.magister_api_dir = ""
        created = db_client.post("/api/tenants", json=_payload("weiter"))
        assert created.json()["job"]["last_completed_step"] == "create_schema"
        tenant_id = created.json()["tenant"]["id"]

        settings.magister_api_dir = configured
        resumed = db_client.post(f"/api/tenants/{tenant_id}/provisioning/resume")
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["tenant"]["status"] == "active"
        assert body["job"]["status"] == "succeeded"
        assert body["job"]["attempts"] == 2
        # Das Passwort war nach dem ersten Lauf verloren; der Migrationsschritt
        # dreht es neu, statt zu raten — und sagt es.
        migrate = [s for s in body["job"]["steps"] if s["step"] == "migrate"]
        assert migrate[-1]["ok"] and "Passwort neu gesetzt" in migrate[-1]["detail"]
        assert body["role_password"], "das neue Passwort muss zurückkommen"
        # create_role steht nur einmal im Protokoll: nicht von vorn.
        assert sum(1 for s in body["job"]["steps"] if s["step"] == "create_role") == 1

        again = db_client.post(f"/api/tenants/{tenant_id}/provisioning/resume")
        assert again.status_code == 409, "ein fertiger Auftrag wird nicht erneut gefahren"
