"""Die Fläche der Kunden-API in beiden Betriebsarten (ADR-0017 D1).

Der Contract-Test aus Phase 3. Er prüft **beide** Richtungen, und das ist der
Punkt: die Fläche hat seit ADR-0017 zwei Betriebsarten, und eine Zweiteilung
ohne Test ist eine Behauptung.

* **Gehostet** (eine Konsolen-URL steht): keine System- und keine
  Rechte-Matrix-Route. Nicht „mit einer Prüfung davor" — gar nicht da.
* **Einzelinstallation** (keine Konsole): alles wie bisher. Eine Gemeinde mit
  einem Server ist ihr eigener Betreiber, und ihr die Konfiguration
  wegzunehmen wäre keine Härtung, sondern ein Ausfall.

Der Test ist absichtlich als **Muster über Pfade** geschrieben und nicht als
Zählung. Eine Zahl („höchstens 137 Routen") schlägt bei jeder neuen
Fachroute fehl und wird dann hochgesetzt, bis niemand mehr hinsieht.
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI

from magister_api.config import Settings
from magister_api.main import create_app

#: Pfade, die es in der gehosteten Betriebsart **nicht** geben darf.
#: Systemkonfiguration und die Rechte-Matrix gehören dem Betreiber
#: (ADR-0017 D1).
FORBIDDEN_WHEN_HOSTED = (
    re.compile(r"^/admin/app-settings"),
    re.compile(r"^/admin/rbac"),
)

#: Pfade, die in **beiden** Betriebsarten da sein müssen. Die Gegenprobe:
#: ohne sie könnte der Filter zu viel wegnehmen und der Test wäre trotzdem
#: grün.
#:
#: `/admin/users/{guid}/roles` ist die Rollen*zuweisung* an Personen und
#: bleibt beim Kunden (Entscheid E2) — nur die Rechte-*Matrix* (was eine Rolle
#: darf) zieht in die Konsole.
REQUIRED_ALWAYS = (
    "/admin/users/{ad_object_guid}/roles",
    "/admin/modules",
    "/me/modules",
    "/audit/events",
    "/users",
    "/classes",
)

BASE = dict(
    audit_key="k" * 32,
    session_secret="s" * 32,
    csrf_secret="c" * 32,
)


def _paths(app: FastAPI) -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")}


@pytest.fixture(scope="module")
def hosted_paths() -> set[str]:
    app = create_app(
        Settings(
            **BASE,  # type: ignore[arg-type]
            console_registry_url="https://console.intern:4444/api/tenants/registry",
            console_registry_token="t",  # type: ignore[arg-type]
        )
    )
    return _paths(app)


@pytest.fixture(scope="module")
def onprem_paths() -> set[str]:
    return _paths(create_app(Settings(**BASE)))  # type: ignore[arg-type]


class TestHostedHasNoSystemSurface:
    def test_no_forbidden_path_is_mounted(self, hosted_paths: set[str]) -> None:
        offenders = sorted(
            p for p in hosted_paths if any(f.match(p) for f in FORBIDDEN_WHEN_HOSTED)
        )
        assert offenders == [], (
            f"Diese Routen gehören dem Betreiber und dürfen in der gehosteten "
            f"Betriebsart nicht in der Kunden-API stehen: {offenders}. "
            "Wer einen solchen Router hinzufügt, trägt ihn in "
            "magister_api.modules.settings.PLATFORM_OWNED_ROUTERS ein (ADR-0017 D1)."
        )

    def test_the_business_surface_is_untouched(self, hosted_paths: set[str]) -> None:
        missing = [p for p in REQUIRED_ALWAYS if p not in hosted_paths]
        assert missing == [], f"Die Härtung hat zu viel weggenommen: {missing} fehlen."


class TestOnPremKeepsEverything:
    def test_the_system_surface_is_there(self, onprem_paths: set[str]) -> None:
        """Eine Gemeinde mit einem Server ist ihr eigener Betreiber.

        ADR-0016 D9 in Worten, hier als Prüfung: die Härtung gilt dort, wo
        mehrere Kunden auf einer Maschine liegen.
        """
        assert "/admin/app-settings" in onprem_paths
        assert "/admin/rbac" in onprem_paths
        assert "/admin/rbac/roles/{key}/capabilities" in onprem_paths

    def test_the_business_surface_is_there_too(self, onprem_paths: set[str]) -> None:
        missing = [p for p in REQUIRED_ALWAYS if p not in onprem_paths]
        assert missing == []


class TestTheDifferenceIsExactlyTheTwoRouters:
    def test_nothing_else_disappears(self, hosted_paths: set[str], onprem_paths: set[str]) -> None:
        """Der Filter nimmt genau das weg, was er wegnehmen soll.

        Ohne diese Prüfung könnte ein Tippfehler in
        `PLATFORM_OWNED_ROUTERS` einen Fachrouter mitnehmen, und die zwei
        Tests oben blieben grün.
        """
        removed = sorted(onprem_paths - hosted_paths)
        assert removed == [
            "/admin/app-settings",
            "/admin/rbac",
            "/admin/rbac/roles",
            "/admin/rbac/roles/{key}",
            "/admin/rbac/roles/{key}/capabilities",
        ]

    def test_hosted_adds_nothing(self, hosted_paths: set[str], onprem_paths: set[str]) -> None:
        # Die gehostete Betriebsart ist eine Verkleinerung, keine andere API.
        assert sorted(hosted_paths - onprem_paths) == []
