"""M6 Phase 3: a disabled module's routes are blocked at request time.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
This module deliberately does NOT enable the company module, so it stays off
(school profile default).
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_disabled_module_routes_return_404(as_schulleitung_a: AsyncClient) -> None:
    # company is off by default -> its routes 404 with module_disabled.
    r = await as_schulleitung_a.get("/departments")
    assert r.status_code == 404
    assert r.json()["detail"] == "module_disabled"


async def test_enabled_module_routes_pass(as_schulleitung_a: AsyncClient) -> None:
    # school is on by default -> its routes are reachable (guard passes).
    r = await as_schulleitung_a.get("/classes")
    assert r.status_code == 200


async def test_platform_routes_are_never_blocked(as_admin: AsyncClient) -> None:
    # platform is non-toggleable -> no guard.
    r = await as_admin.get("/admin/modules")
    assert r.status_code == 200
