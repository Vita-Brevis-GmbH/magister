"""Welche Mandanten das CLI sieht — und warum das nicht die Umgebung entscheidet.

Der Fehler, den diese Datei festnagelt, war still und teuer: `magister-cli
tenants` baute die Registry mit `build_registry()`, also **nur** aus der
Umgebung. Im gehosteten Betrieb steht die Wahrheit in der Konsole; die
Umgebung nennt dort keinen einzigen Mandanten. Das Werkzeug sah deshalb genau
einen erfundenen Kunden („default", Schema `public`) — und
`tenants migrate`, der Ablauf, den ADR-0021 D1 ausdrücklich auf den
Anwendungsserver legt, hätte die echten Kundenschemas nie angefasst.

Aufgefallen beim Aufbau der Entwicklungsumgebung: zwei Kunden in der Konsole,
`tenants list` zeigte einen.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from magister_api.cli import tenants as cli
from magister_api.config import Settings
from magister_api.tenancy.console_registry import ConsoleUnavailableError
from magister_api.tenancy.registry import Tenant, TenantRegistry, TenantStatus


def _settings(**over: Any) -> Settings:
    base = Settings(
        database_url="postgresql+asyncpg://app:pw@db/magister",
        audit_key=SecretStr("a" * 40),
        session_secret=SecretStr("b" * 40),
    )
    return base.model_copy(update=over)


CONSOLE = {
    "console_registry_url": "https://console.mgmt.vitabrevis.ch:4444/api/tenants/registry",
    "console_registry_token": SecretStr("token"),
    "console_management_marker": SecretStr("marker"),
}


def _two_tenants() -> TenantRegistry:
    return TenantRegistry(
        [
            Tenant(
                slug=slug,
                name=slug.title(),
                dsn=f"postgresql+asyncpg://r_{slug}:pw@db/magister",
                schema_name=f"t_{slug}",
                db_role=f"r_{slug}",
                schema_version="0046_operator_access",
                status=TenantStatus.ACTIVE,
                hostname=f"{slug}.mgmt.vitabrevis.ch",
            )
            for slug in ("thun", "bern")
        ]
    )


def test_without_a_console_the_environment_decides() -> None:
    """Der On-prem-Fall bleibt, wie er war: ein Mandant aus dem DSN."""
    registry = cli.load_registry(_settings())
    assert [t.slug for t in registry.tenants] == ["default"]


def test_with_a_console_the_console_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake(url: str, *, token: str, management_marker: str = "") -> TenantRegistry:
        seen.update(url=url, token=token, marker=management_marker)
        return _two_tenants()

    monkeypatch.setattr(cli, "fetch_registry", _fake)
    registry = cli.load_registry(_settings(**CONSOLE))

    assert sorted(t.slug for t in registry.tenants) == ["bern", "thun"]
    assert seen["url"] == CONSOLE["console_registry_url"]
    # Beide Nachweise gehen mit: Token UND Marker. Ohne den Marker verwirft
    # die Konsole die Anfrage mit 404 (ADR-0015 D1), und das sähe hier aus
    # wie „keine Kunden vorhanden".
    assert seen["token"] == "token"
    assert seen["marker"] == "marker"


def test_an_unreachable_console_stops_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein stiller Rückfall auf die Umgebung.

    Im laufenden Betrieb gilt der letzte gute Stand weiter (ADR-0013 D4) —
    dort ist Bedienen wichtiger als Aktualität. Hier ist es umgekehrt: der
    nächste Schritt schreibt in Kundenschemas, und eine Liste, von der
    niemand weiss, wie alt sie ist, ist dafür die falsche Grundlage. Ein
    Rückfall wäre zudem genau die eine erfundene Zeile („default").
    """

    async def _boom(url: str, *, token: str, management_marker: str = "") -> TenantRegistry:
        raise ConsoleUnavailableError("Konsole antwortet nicht")

    monkeypatch.setattr(cli, "fetch_registry", _boom)
    with pytest.raises(ConsoleUnavailableError):
        cli.load_registry(_settings(**CONSOLE))
