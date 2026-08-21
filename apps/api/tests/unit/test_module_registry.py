"""M6 Phase 0: the module registry must preserve the historical route set.

Phase 0 is a pure refactor — grouping the routers into a ``platform`` and a
``school`` module and mounting them via the registry must not add, drop or
change any route, and every registered module's routes must actually be mounted.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from magister_api.main import create_app
from magister_api.modules.registry import ALL_MODULES, enabled_modules


def _app_route_keys() -> set[tuple[str, frozenset[str]]]:
    app = create_app()
    return {(r.path, frozenset(r.methods or ())) for r in app.routes if isinstance(r, APIRoute)}


def test_every_enabled_module_router_is_mounted() -> None:
    mounted = _app_route_keys()
    for module in enabled_modules():
        for router in module.routers:
            for route in router.routes:
                if isinstance(route, APIRoute):
                    key = (route.path, frozenset(route.methods or ()))
                    assert key in mounted, f"{module.id}: {route.path} {route.methods} not mounted"


def test_router_count() -> None:
    # 25 routers were hard-listed in create_app() before the registry seam;
    # M6 Phase 1 adds admin_modules (platform) → 26; Phase 2 adds departments +
    # department_people (company) → 28. A drop or dup would change this count.
    total = sum(len(m.routers) for m in ALL_MODULES)
    assert total == 28


def test_module_ids_unique_and_expected() -> None:
    ids = [m.id for m in ALL_MODULES]
    assert ids == list(dict.fromkeys(ids)), "duplicate module id"
    assert {"platform", "school"} <= set(ids)


def test_school_depends_on_platform() -> None:
    from magister_api.modules.catalog import get_meta

    meta = get_meta("school")
    assert meta is not None
    assert "platform" in meta.depends_on


def test_healthz_still_present() -> None:
    assert ("/healthz", frozenset({"GET"})) in _app_route_keys()
