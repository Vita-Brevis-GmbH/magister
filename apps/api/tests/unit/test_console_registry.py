"""Registry von der Konsole: Verweise statt DSNs, letzter guter Stand hält.

Die zwei Zusagen aus ADR-0013 D4:

- Kein Kunden-Request liest je die Konsolen-Datenbank — der Abruf ist ein
  Hintergrundvorgang, im heissen Pfad steht der Zwischenspeicher.
- Ein Ausfall der Konsole lässt jeden Kunden weiterlaufen.
"""

from __future__ import annotations

from typing import Any

import pytest

from magister_api.tenancy.console_registry import (
    ConsoleUnavailableError,
    dsn_env_name,
    registry_from_console_payload,
    resolve_dsn,
)
from magister_api.tenancy.registry import TenantConfigError, TenantStatus

DSN_A = "postgresql+asyncpg://r_alpha:pw@db/magister"
DSN_B = "postgresql+asyncpg://r_beta:pw@db/magister"


def _entry(slug: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": slug,
        "name": f"Gemeinde {slug}",
        "hostname": f"{slug}.magister.ch",
        "status": "active",
        "dsn_ref": f"tenant_{slug}",
        "schema_name": f"t_{slug}",
        "db_role": f"r_{slug}",
        "schema_version": "0044_local_admin_totp",
    }
    base.update(over)
    return base


ENV = {
    "MAGISTER_TENANT_DSN_TENANT_ALPHA": DSN_A,
    "MAGISTER_TENANT_DSN_TENANT_BETA": DSN_B,
}


class TestDsnResolution:
    def test_the_env_name_is_the_upper_cased_ref(self) -> None:
        assert dsn_env_name("tenant_alpha") == "MAGISTER_TENANT_DSN_TENANT_ALPHA"

    def test_a_missing_dsn_names_the_variable(self) -> None:
        # Der Betreiber muss aus der Meldung wissen, was er setzen soll.
        with pytest.raises(TenantConfigError, match="MAGISTER_TENANT_DSN_TENANT_GAMMA"):
            resolve_dsn("tenant_gamma", environ={})

    def test_an_empty_dsn_counts_as_missing(self) -> None:
        with pytest.raises(TenantConfigError):
            resolve_dsn("tenant_alpha", environ={"MAGISTER_TENANT_DSN_TENANT_ALPHA": "   "})


class TestPayloadTranslation:
    def test_two_tenants_become_a_valid_registry(self) -> None:
        registry = registry_from_console_payload([_entry("alpha"), _entry("beta")], environ=ENV)
        assert {t.slug for t in registry.tenants} == {"alpha", "beta"}
        hit = registry.resolve_host("beta.magister.ch")
        assert hit is not None and hit.dsn == DSN_B

    def test_a_tenant_without_a_dsn_is_skipped_not_fatal(self) -> None:
        """Sonst hielte ein unfertiger Eintrag die ganze Installation an.

        Der übersprungene Kunde ist danach unbekannt und antwortet mit 404 —
        was zutrifft, denn erreichen könnte man ihn ohnehin nicht.
        """
        registry = registry_from_console_payload([_entry("alpha"), _entry("ohnedsn")], environ=ENV)
        assert {t.slug for t in registry.tenants} == {"alpha"}

    def test_an_unknown_status_is_skipped(self) -> None:
        registry = registry_from_console_payload(
            [_entry("alpha"), _entry("beta", status="halb")], environ=ENV
        )
        assert {t.slug for t in registry.tenants} == {"alpha"}

    def test_an_empty_result_is_refused(self) -> None:
        # Ein leeres Ergebnis darf den letzten guten Stand NICHT ersetzen,
        # sonst setzt ein Fehler in der Konsole alle Kunden auf 404.
        with pytest.raises(ConsoleUnavailableError):
            registry_from_console_payload([], environ=ENV)
        with pytest.raises(ConsoleUnavailableError):
            registry_from_console_payload([_entry("ohnedsn")], environ=ENV)

    def test_the_registry_rules_still_apply_to_console_data(self) -> None:
        """Die Konsole ist eine Quelle, keine Autorität.

        Zwei Kunden mit derselben Anmelderolle im DSN wären genau der Fall,
        der die Trennung aufhebt — auch wenn die Konsole es so liefert.
        """
        shared = {
            "MAGISTER_TENANT_DSN_TENANT_ALPHA": DSN_A,
            "MAGISTER_TENANT_DSN_TENANT_BETA": DSN_A,
        }
        with pytest.raises(TenantConfigError, match="eigene"):
            registry_from_console_payload([_entry("alpha"), _entry("beta")], environ=shared)

    def test_non_active_tenants_are_kept(self) -> None:
        # Die Datenebene braucht sie, um 503 statt 404 zu antworten.
        registry = registry_from_console_payload(
            [_entry("alpha"), _entry("beta", status="suspended")], environ=ENV
        )
        beta = registry.by_slug("beta")
        assert beta is not None and beta.status is TenantStatus.SUSPENDED

    def test_the_console_id_is_carried_for_connector_jobs(self) -> None:
        """Die Datenebene braucht sie, um Connector-Aufträge zu adressieren.

        Kein Geheimnis: wer die Id hat, kann ohne Konsolen-Token nichts damit
        tun. Fehlt sie, bleibt der Connector-Rücken für diesen Kunden aus und
        Magister spricht das AD wie bisher an.
        """
        registry = registry_from_console_payload(
            [_entry("alpha", id="7f000000-0000-0000-0000-000000000001")], environ=ENV
        )
        assert registry.tenants[0].console_id == "7f000000-0000-0000-0000-000000000001"

    def test_a_missing_console_id_is_not_an_error(self) -> None:
        registry = registry_from_console_payload([_entry("alpha")], environ=ENV)
        assert registry.tenants[0].console_id is None

    def test_the_payload_carries_no_dsn_field(self) -> None:
        """Gegenprobe zur Zusage: der Verweis genügt, ein DSN wird ignoriert.

        Selbst wenn jemand einen DSN in die Antwort schmuggelt, benutzt die
        Datenebene ihren eigenen — der Kanal kann keinen Datenbankzugang
        verteilen.
        """
        smuggled = _entry("alpha", dsn="postgresql+asyncpg://boese@evil/db")
        registry = registry_from_console_payload([smuggled], environ=ENV)
        assert registry.tenants[0].dsn == DSN_A


class TestLastGoodState:
    """Ein Ausfall der Konsole ist eine Störung in der Verwaltung, kein
    Ausfall des Betriebs (ADR-0013 D4)."""

    @pytest.mark.asyncio
    async def test_an_unreachable_console_leaves_the_registry_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from magister_api.config import Settings
        from magister_api.tenancy import context

        settings = Settings(
            console_registry_url="http://console.invalid/api/tenants/registry",
            console_registry_token="t",  # type: ignore[arg-type]
            audit_key="k",  # type: ignore[arg-type]
            session_secret="s",  # type: ignore[arg-type]
            csrf_secret="c",  # type: ignore[arg-type]
        )
        context.init_tenancy(settings)
        before = context.get_registry().tenants

        async def _boom(*_: object, **__: object) -> None:
            raise ConsoleUnavailableError("Konsole nicht erreichbar: Testfall")

        monkeypatch.setattr(context, "fetch_registry", _boom)
        replaced = await context.refresh_from_console(settings)

        assert replaced is False
        assert context.get_registry().tenants == before
        await context.dispose_tenancy()

    @pytest.mark.asyncio
    async def test_a_good_answer_replaces_the_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from magister_api.config import Settings
        from magister_api.tenancy import context
        from magister_api.tenancy.registry import TenantRegistry

        settings = Settings(
            console_registry_url="http://console.test/api/tenants/registry",
            console_registry_token="t",  # type: ignore[arg-type]
            audit_key="k",  # type: ignore[arg-type]
            session_secret="s",  # type: ignore[arg-type]
            csrf_secret="c",  # type: ignore[arg-type]
        )
        context.init_tenancy(settings)
        fresh = registry_from_console_payload([_entry("alpha"), _entry("beta")], environ=ENV)

        async def _ok(*_: object, **__: object) -> TenantRegistry:
            return fresh

        monkeypatch.setattr(context, "fetch_registry", _ok)
        assert await context.refresh_from_console(settings) is True
        assert {t.slug for t in context.get_registry().tenants} == {"alpha", "beta"}
        await context.dispose_tenancy()

    @pytest.mark.asyncio
    async def test_without_a_console_url_nothing_is_fetched(self) -> None:
        from magister_api.config import Settings
        from magister_api.tenancy import context

        settings = Settings(
            audit_key="k",  # type: ignore[arg-type]
            session_secret="s",  # type: ignore[arg-type]
            csrf_secret="c",  # type: ignore[arg-type]
        )
        context.init_tenancy(settings)
        assert await context.refresh_from_console(settings) is False
        await context.dispose_tenancy()
