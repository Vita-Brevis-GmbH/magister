"""Welcher AD-Rücken gilt — und dass beide Aufrufer denselben nehmen (ADR-0022 D2).

Der Fehler, den diese Datei festnagelt, war real und still: der Anfragepfad
wählte bei einem gehosteten Kunden den Connector-Agenten, die wiederkehrende
Schleife nahm fest den direkten LDAP-Rücken. Für einen Kunden, dessen
Verzeichnis nur über den Agenten erreichbar ist, hiess das: Passwort-Reset
ging, der nächtliche Abgleich lief ins Leere — jede Nacht, mit einem
`ad_sync_failed` im Protokoll, das nach einem AD-Ausfall aussah.

Alles hier ist DB-frei: gebaut wird nur der Client, nicht verbunden.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request
from pydantic import SecretStr

from magister_api.ad.client import AdClient
from magister_api.ad.connector_client import AdConnectorClient
from magister_api.ad.factory import build_ad_client
from magister_api.ad.rpc_client import AdRpcClient
from magister_api.config import Settings
from magister_api.routers.admin_sync import get_ad_client
from magister_api.services import ad_sync_scheduler
from magister_api.tenancy.registry import Tenant, TenantStatus


def _tenant(*, console_id: str | None) -> Tenant:
    return Tenant(
        slug="thun",
        name="Thun",
        dsn="postgresql+asyncpg://r_thun:x@db/magister",
        schema_name="t_thun",
        db_role="r_thun",
        schema_version="",
        status=TenantStatus.ACTIVE,
        console_id=console_id,
        hostname="thun.magister.ch",
    )


def _settings(**overrides: Any) -> Settings:
    base = Settings(
        database_url="postgresql+asyncpg://x:y@db/magister",
        audit_key=SecretStr("a" * 40),
        session_secret=SecretStr("b" * 40),
    )
    return base.model_copy(update=overrides)


HOSTED = {
    "ad_connector_enabled": True,
    "console_registry_url": "https://console.magister.ch:4444/api/tenants/registry",
    "console_registry_token": SecretStr("token"),
    "console_management_marker": SecretStr("marker"),
}


class TestTheChoice:
    def test_rpc_wins_when_configured(self) -> None:
        """ADR-0011 zuerst: ein Container ohne Verzeichnis-Zugangsdaten."""
        base = _settings(
            ad_rpc_url="http://magister-api-ad:8000",
            ad_rpc_secret=SecretStr("s"),
            **HOSTED,
        )
        client = build_ad_client(base, base, _tenant(console_id="c1"))
        assert isinstance(client, AdRpcClient)

    def test_hosted_tenant_gets_the_connector(self) -> None:
        base = _settings(**HOSTED)
        client = build_ad_client(base, base, _tenant(console_id="c1"))
        assert isinstance(client, AdConnectorClient)

    def test_without_a_console_id_it_stays_direct(self) -> None:
        """Ein Kunde ohne Konsolen-Id ist der On-prem-Fall (ADR-0013 D8)."""
        base = _settings(**HOSTED)
        client = build_ad_client(base, base, _tenant(console_id=None))
        assert type(client) is AdClient

    def test_without_the_connector_switch_it_stays_direct(self) -> None:
        base = _settings(**{**HOSTED, "ad_connector_enabled": False})
        client = build_ad_client(base, base, _tenant(console_id="c1"))
        assert type(client) is AdClient

    def test_the_effective_settings_reach_the_client(self) -> None:
        """Transport aus den Prozess-Einstellungen, Verzeichnis aus den wirksamen.

        Beides an einen Client zu geben wäre die naheliegende Vereinfachung
        und falsch: die Suchbasis gehört dem Kunden und steht in
        `app_settings`, die Verbindung zur Konsole gehört der Installation.
        """
        base = _settings(**HOSTED)
        effective = base.model_copy(update={"ad_users_search_base": "OU=Thun,DC=x,DC=y"})
        client = build_ad_client(base, effective, _tenant(console_id="c1"))
        assert client._settings.ad_users_search_base == "OU=Thun,DC=x,DC=y"


class TestBothCallersAgree:
    """Die eigentliche Zusage: **eine** Entscheidung, zwei Aufrufer."""

    def test_the_loop_does_not_choose_for_itself(self) -> None:
        """Die Vorgabe der Schleife ist genau die Fabrik.

        Ein eigener Vorgabewert (früher: `AdClient`) ist die Stelle, an der
        die beiden Wege auseinanderlaufen — er sieht in jedem Review harmlos
        aus und ist es nicht.
        """
        for fn in (ad_sync_scheduler.sync_tenant, ad_sync_scheduler.run_ad_sync_loop):
            defaults = fn.__kwdefaults__ or {}
            assert defaults["client_factory"] is build_ad_client, (
                f"{fn.__name__} baut den AD-Rücken selbst statt über ad.factory"
            )

    def test_the_request_path_builds_the_same_backend(self) -> None:
        """Und der Anfragepfad ebenso — geprüft am Ergebnis, nicht am Code."""
        base = _settings(**HOSTED)
        tenant = _tenant(console_id="c1")
        # Ein Request, wie ihn die Auflösungs-Middleware hinterlässt: Mandant
        # im Zustand, Prozess-Einstellungen an der App.
        scope: dict[str, Any] = {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(settings=base)),
            "state": {"tenant": tenant},
            "headers": [],
        }
        request = Request(cast(Any, scope))
        request.state.tenant = tenant

        from_request = get_ad_client(request, base)
        from_factory = build_ad_client(base, base, tenant)
        assert type(from_request) is type(from_factory) is AdConnectorClient


@pytest.mark.parametrize("console_id", ["c1", None])
def test_the_choice_never_raises_for_a_valid_tenant(console_id: str | None) -> None:
    base = _settings(**HOSTED)
    assert build_ad_client(base, base, _tenant(console_id=console_id)) is not None
