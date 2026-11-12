"""Auflösung, Wartungs-Schranke, Kopf-Version, Kundenschlüssel.

ADR-0013 D3 und D7 sowie ADR-0016 D8. Die vier Schranken stehen in dieser
Reihenfolge vor jeder Anfrage, und jede hat einen eigenen Grund; die letzte
ist der Kundenschlüssel, ohne den kein Audit-Ereignis geschrieben werden kann.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from magister_api.config import CONCURRENCY_HEADROOM, Settings
from magister_api.tenancy.keys import ENV_AUDIT_KEY, MIN_KEY_LENGTH
from magister_api.tenancy.middleware import ConcurrencyGate, make_tenant_middleware
from magister_api.tenancy.registry import Tenant, TenantRegistry, TenantStatus
from magister_api.tenancy.version import HEAD_REVISION


#: Bei mehr als einem Mandanten braucht jeder seinen eigenen Kundenschlüssel
#: (ADR-0016 D8). Die Tests hier prüfen die Auflösung, nicht die
#: Schlüsselverwaltung — also werden die Schlüssel gesetzt, ausser dort, wo
#: gerade ihr Fehlen geprüft wird.
@pytest.fixture(autouse=True)
def _tenant_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for slug in ("alpha", "beta", "gamma", "default", "einzeln"):
        monkeypatch.setenv(ENV_AUDIT_KEY.format(ref=slug.upper()), slug * MIN_KEY_LENGTH)


def _tenant(slug: str, **over: object) -> Tenant:
    base: dict[str, object] = {
        "slug": slug,
        "name": slug,
        "dsn": f"postgresql+asyncpg://r_{slug}@db/magister",
        "schema_name": f"t_{slug}",
        "db_role": f"r_{slug}",
        "schema_version": HEAD_REVISION,
        "status": TenantStatus.ACTIVE,
        "hostname": f"{slug}.magister.ch",
    }
    base.update(over)
    return Tenant(**base)  # type: ignore[arg-type]


def _app(
    registry: TenantRegistry,
    *,
    gate: ConcurrencyGate | None = None,
    explode: bool = False,
) -> TestClient:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        tenant: Tenant = request.state.tenant
        return {"slug": tenant.slug}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if explode:
        # Eine Route, die fliegt — für die Frage, ob ihr Platz zurückkommt.
        @app.get("/boom")
        async def boom() -> dict[str, str]:
            raise RuntimeError("kaputt")

    app.middleware("http")(make_tenant_middleware(lambda: registry, gate=gate))
    return TestClient(app)


class TestTenantKeyGate:
    """ADR-0016 D8: ohne eigenen Kundenschlüssel wird nicht bedient."""

    def test_a_tenant_without_a_key_gets_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Und zwar **vor** der ersten Abfrage, nicht mitten in der Mutation.

        Der andere Weg wäre ein stiller Rückfall auf den installationsweiten
        Schlüssel. Damit liefe alles — und die Löschzusage an den Kunden wäre
        unwahr, weil sein Schlüssel nichts wäre, was man einzeln vernichten
        kann.
        """
        monkeypatch.delenv(ENV_AUDIT_KEY.format(ref="BETA"), raising=False)
        client = _app(TenantRegistry([_tenant("alpha"), _tenant("beta")]))
        resp = client.get("/whoami", headers={"host": "beta.magister.ch"})
        assert resp.status_code == 503
        assert resp.json() == {"detail": "maintenance"}
        # Der Nachbar wird weiter bedient: ein fehlender Schlüssel ist das
        # Problem eines Kunden, nicht der Installation.
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 200

    def test_the_response_does_not_name_the_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Was der Betreiber falsch konfiguriert hat, ist keine Auskunft für Anwender."""
        monkeypatch.delenv(ENV_AUDIT_KEY.format(ref="BETA"), raising=False)
        client = _app(TenantRegistry([_tenant("alpha"), _tenant("beta")]))
        body = client.get("/whoami", headers={"host": "beta.magister.ch"}).text
        assert "MAGISTER_TENANT_AUDIT_KEY" not in body

    def test_a_single_tenant_needs_no_own_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Eine bestehende Installation läuft nach dem Update unverändert weiter."""
        monkeypatch.delenv(ENV_AUDIT_KEY.format(ref="EINZELN"), raising=False)
        monkeypatch.setenv("MAGISTER_AUDIT_KEY", "x" * MIN_KEY_LENGTH)
        from magister_api.config import reset_settings_cache

        reset_settings_cache()
        try:
            client = _app(TenantRegistry([_tenant("einzeln")]))
            assert client.get("/whoami", headers={"host": "einzeln.magister.ch"}).status_code == 200
        finally:
            reset_settings_cache()


class TestResolution:
    def test_a_known_host_reaches_the_handler(self) -> None:
        client = _app(TenantRegistry([_tenant("alpha"), _tenant("beta")]))
        resp = client.get("/whoami", headers={"host": "beta.magister.ch"})
        assert resp.status_code == 200
        assert resp.json() == {"slug": "beta"}

    def test_an_unknown_host_is_404(self) -> None:
        """404, nicht 400: eine unterscheidende Antwort verrät die Kundenliste."""
        client = _app(TenantRegistry([_tenant("alpha"), _tenant("beta")]))
        resp = client.get("/whoami", headers={"host": "gamma.magister.ch"})
        assert resp.status_code == 404
        assert resp.json() == {"detail": "unknown_tenant"}

    def test_the_forwarded_host_wins(self) -> None:
        # Caddy setzt X-Forwarded-Host; der Host-Header ist dann der interne.
        client = _app(TenantRegistry([_tenant("alpha"), _tenant("beta")]))
        resp = client.get(
            "/whoami",
            headers={"host": "api:8000", "x-forwarded-host": "alpha.magister.ch"},
        )
        assert resp.json() == {"slug": "alpha"}

    def test_the_health_probe_needs_no_tenant(self) -> None:
        # Sonst startet ein Orchestrierer den Container endlos neu, während
        # ihm nur eine Zeile Konfiguration fehlt.
        client = _app(TenantRegistry([_tenant("alpha")]))
        assert client.get("/healthz", headers={"host": "nirgendwo.test"}).status_code == 200

    def test_a_single_tenant_answers_for_any_host(self) -> None:
        client = _app(TenantRegistry([_tenant("alpha", hostname=None, db_role=None)]))
        assert client.get("/whoami", headers={"host": "was.auch.immer"}).status_code == 200


class TestMaintenanceGate:
    @pytest.mark.parametrize(
        "status", [TenantStatus.SUSPENDED, TenantStatus.PROVISIONING, TenantStatus.OFFBOARDING]
    )
    def test_a_non_active_tenant_gets_503(self, status: TenantStatus) -> None:
        client = _app(TenantRegistry([_tenant("alpha", status=status)]))
        resp = client.get("/whoami", headers={"host": "alpha.magister.ch"})
        assert resp.status_code == 503
        assert resp.json() == {"detail": "maintenance"}
        assert resp.headers["Retry-After"] == "120"

    def test_a_schema_behind_the_code_gets_503(self) -> None:
        """Lieber Wartung als eine plausibel falsche Antwort (ADR-0013 D7)."""
        client = _app(TenantRegistry([_tenant("alpha", schema_version="0012_alt")]))
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 503

    def test_an_unknown_schema_version_is_served(self) -> None:
        # Der Bestand vor dem Umzug trägt keinen Stand; er darf nicht
        # stillstehen, nur weil die Registry noch aus der Umgebung kommt.
        client = _app(TenantRegistry([_tenant("alpha", schema_version="")]))
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 200


class TestHeadRevision:
    def test_the_constant_matches_the_real_alembic_head(self) -> None:
        """Sonst driftet die Wartungs-Schranke unbemerkt.

        Die Konstante existiert, damit die Anwendung ihre Schema-Version ohne
        Alembic-Import kennt. Damit sie stimmt, wird sie hier gegen die
        Migrationsdateien geprüft — Abweichung fällt in CI auf, nicht im Betrieb.
        """
        versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
        revisions: dict[str, str | None] = {}
        for path in versions.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            rev = _extract(text, "revision")
            down = _extract(text, "down_revision")
            if rev:
                revisions[rev] = down
        assert revisions, "keine Migrationen gefunden"
        parents = {down for down in revisions.values() if down}
        heads = sorted(set(revisions) - parents)
        assert heads == [HEAD_REVISION], (
            f"HEAD_REVISION={HEAD_REVISION!r} passt nicht zum Alembic-Kopf {heads!r}. "
            "Nach einer neuen Migration muss magister_api/tenancy/version.py mit."
        )


def _extract(text: str, name: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}:") or stripped.startswith(f"{name} ="):
            _, _, rhs = stripped.partition("=")
            value = rhs.strip()
            if value in ("None", ""):
                return None
            return value.strip("\"'")
    return None


class TestTheConcurrencyCeiling:
    """ADR-0021 D3: ein Kunde kann den Prozess nicht für alle belegen."""

    def test_over_the_ceiling_this_tenant_gets_503(self) -> None:
        """Und der Grund steht im Rumpf, nicht nur im Statuscode."""
        registry = TenantRegistry([_tenant("alpha"), _tenant("beta")])
        gate = ConcurrencyGate(limit=1)
        # Ein Platz ist belegt — als wäre gerade eine Anfrage in der Luft.
        assert gate.try_enter("alpha")
        client = _app(registry, gate=gate)
        response = client.get("/whoami", headers={"host": "alpha.magister.ch"})
        assert response.status_code == 503
        assert response.json()["detail"] == "too_busy"
        assert response.headers["Retry-After"] == "2"

    def test_the_ceiling_is_per_tenant(self) -> None:
        """Der eigentliche Punkt: der Nachbar merkt nichts davon."""
        registry = TenantRegistry([_tenant("alpha"), _tenant("beta")])
        gate = ConcurrencyGate(limit=1)
        assert gate.try_enter("alpha")
        client = _app(registry, gate=gate)
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 503
        ok = client.get("/whoami", headers={"host": "beta.magister.ch"})
        assert ok.status_code == 200
        assert ok.json() == {"slug": "beta"}

    def test_a_place_is_released_after_the_request(self) -> None:
        registry = TenantRegistry([_tenant("alpha")])
        gate = ConcurrencyGate(limit=1)
        client = _app(registry, gate=gate)
        for _ in range(3):
            assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 200
        assert gate.in_flight("alpha") == 0

    def test_a_failing_route_releases_its_place(self) -> None:
        """Sonst schrumpft die Decke mit jedem Fehler, bis der Kunde draussen ist.

        Das ist der Grund für das `finally` — und der Fehler, den man ohne
        diesen Test erst nach dem fünften 500 bemerkt.
        """
        registry = TenantRegistry([_tenant("alpha")])
        gate = ConcurrencyGate(limit=2)
        client = _app(registry, gate=gate, explode=True)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                client.get("/boom", headers={"host": "alpha.magister.ch"})
        assert gate.in_flight("alpha") == 0
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 200

    def test_a_404_does_not_take_a_place(self) -> None:
        """Ein unbekannter Hostname soll keine Decke verbrauchen.

        Sonst wäre eine Sonde, die tausend fremde Hostnamen durchprobiert, ein
        Weg, die Decke eines Kunden zu füllen.
        """
        registry = TenantRegistry([_tenant("alpha")])
        gate = ConcurrencyGate(limit=1)
        client = _app(registry, gate=gate)
        assert client.get("/whoami", headers={"host": "fremd.magister.ch"}).status_code == 404
        assert gate.in_flight("alpha") == 0
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 200

    def test_a_maintenance_answer_does_not_take_a_place(self) -> None:
        registry = TenantRegistry([_tenant("alpha", status=TenantStatus.SUSPENDED)])
        gate = ConcurrencyGate(limit=1)
        client = _app(registry, gate=gate)
        assert client.get("/whoami", headers={"host": "alpha.magister.ch"}).status_code == 503
        assert gate.in_flight("alpha") == 0

    def test_the_probes_are_not_counted(self) -> None:
        """`/healthz` läuft ohne Mandanten und damit ohne Decke.

        Eine Sonde, die am Limit eines Kunden scheitert, würde einen gesunden
        Prozess als krank melden.
        """
        registry = TenantRegistry([_tenant("alpha")])
        gate = ConcurrencyGate(limit=1)
        assert gate.try_enter("alpha")
        client = _app(registry, gate=gate)
        assert client.get("/healthz", headers={"host": "alpha.magister.ch"}).status_code == 200


class TestTheGateItself:
    def test_the_limit_is_never_zero(self) -> None:
        """Eine Decke von 0 wäre eine geschlossene Installation."""
        assert ConcurrencyGate(limit=0).limit == 1
        assert ConcurrencyGate(limit=-5).limit == 1

    def test_counting_up_and_down(self) -> None:
        gate = ConcurrencyGate(limit=2)
        assert gate.try_enter("alpha")
        assert gate.try_enter("alpha")
        assert not gate.try_enter("alpha")
        gate.leave("alpha")
        assert gate.in_flight("alpha") == 1
        assert gate.try_enter("alpha")
        gate.leave("alpha")
        gate.leave("alpha")
        assert gate.in_flight("alpha") == 0

    def test_leaving_more_often_than_entering_does_not_go_negative(self) -> None:
        """Sonst wäre ein Zählfehler ein Kunde mit unbegrenzter Decke."""
        gate = ConcurrencyGate(limit=1)
        gate.leave("alpha")
        gate.leave("alpha")
        assert gate.in_flight("alpha") == 0
        assert gate.try_enter("alpha")
        assert not gate.try_enter("alpha")

    def test_the_derived_limit_follows_the_pool(self) -> None:
        """Zwei Zahlen, die zusammengehören, sind eine Zahl und eine Ableitung."""
        settings = Settings(
            audit_key="a" * 40,  # type: ignore[arg-type]
            session_secret="b" * 40,  # type: ignore[arg-type]
            csrf_secret="c" * 40,  # type: ignore[arg-type]
            tenant_pool_size=4,
            tenant_max_overflow=6,
        )
        assert settings.tenant_concurrency_limit() == 4 + 6 + CONCURRENCY_HEADROOM

    def test_an_explicit_limit_wins(self) -> None:
        settings = Settings(
            audit_key="a" * 40,  # type: ignore[arg-type]
            session_secret="b" * 40,  # type: ignore[arg-type]
            csrf_secret="c" * 40,  # type: ignore[arg-type]
            tenant_max_concurrent=3,
        )
        assert settings.tenant_concurrency_limit() == 3
