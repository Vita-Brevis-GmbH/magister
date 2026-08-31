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
    # 32 routers total. M6 #5 regrouped the coarse modules into fine-grained
    # fachfunction modules; the platform carve (10-container split) then split
    # the former single platform module into platform/ad/users/settings and
    # folded document-templates + letters into ``templates`` — all pure
    # redistribution, WITHOUT adding or dropping any route, so the total stays 32.
    total = sum(len(m.routers) for m in ALL_MODULES)
    assert total == 32


def test_module_ids_unique_and_expected() -> None:
    ids = [m.id for m in ALL_MODULES]
    assert ids == list(dict.fromkeys(ids)), "duplicate module id"
    assert {"platform", "classes", "departments"} <= set(ids)


def test_classes_depends_on_platform() -> None:
    from magister_api.modules.catalog import get_meta

    meta = get_meta("classes")
    assert meta is not None
    assert "platform" in meta.depends_on


def test_healthz_still_present() -> None:
    assert ("/healthz", frozenset({"GET"})) in _app_route_keys()


# --- M6 Phase 3 / ADR-0008 D5: split-fähig (per-module container) ----------


def test_enabled_modules_default_is_all() -> None:
    assert enabled_modules() == ALL_MODULES
    assert enabled_modules([]) == ALL_MODULES


def test_enabled_modules_container_subset_keeps_platform() -> None:
    ids = [m.id for m in enabled_modules(["departments"])]
    assert "platform" in ids  # base is always mounted (auth/session/me)
    assert "departments" in ids
    assert "classes" not in ids  # a school module is NOT mounted in this container


def test_enabled_modules_rejects_unknown_id() -> None:
    import pytest

    from magister_api.modules.registry import UnknownModuleError

    with pytest.raises(UnknownModuleError):
        enabled_modules(["nope"])


def test_container_app_mounts_only_selected_module() -> None:
    from magister_api.config import get_settings

    settings = get_settings().model_copy(update={"container_modules": ["departments"]})
    app = create_app(settings)
    keys = {(r.path, frozenset(r.methods or ())) for r in app.routes if isinstance(r, APIRoute)}
    paths = {p for p, _ in keys}
    # platform base + departments are served; classes routes are not.
    assert "/departments" in paths
    assert any(p.startswith("/auth") for p in paths)  # platform auth present
    assert "/classes" not in paths
    assert ("/healthz", frozenset({"GET"})) in keys
