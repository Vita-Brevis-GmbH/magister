"""M6 Phase 3: module-contract fitness functions (ADR-0008 D8).

These are architecture tests, not feature tests: they walk the assembled app
and assert the module seam keeps holding as routers/modules are added. They
fail CI the moment a new endpoint forgets authentication, a new module is
mounted without catalog policy (so it could be neither toggled nor guarded),
or the Phase-3 request guard stops covering a toggleable module.

They need no database — ``create_app`` only wires routers.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from magister_api.main import create_app
from magister_api.modules import catalog
from magister_api.modules.registry import enabled_modules

# Routes that are intentionally reachable without authentication. Every other
# ``magister_api`` route MUST pull in ``get_current_user``. Keep this list
# minimal and explicit — it is the audited surface of the app's front door.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("/healthz", "GET"),
        ("/runtime", "GET"),  # per-container introspection; internal-only, not routed by Caddy
        ("/auth/login", "GET"),  # OIDC redirect start
        ("/auth/callback", "GET"),  # OIDC redirect return
        ("/auth/capabilities", "GET"),  # login-screen feature probe
        ("/auth/login/ad", "POST"),  # AD credential login
        ("/auth/login/local", "POST"),  # local-admin fallback login
    }
)

_AUTH_MARKER = "get_current_user"
_GUARD_MARKER = "make_module_guard.<locals>._guard"


def _dependant_callables(dep: Dependant) -> Iterator[str]:
    """Every callable qualname in a route's dependency tree (depth-first)."""
    if dep.call is not None:
        yield dep.call.__qualname__
    for sub in dep.dependencies:
        yield from _dependant_callables(sub)


def _own_routes() -> list[APIRoute]:
    """APIRoutes defined by our own code (skips FastAPI's docs/openapi)."""
    app = create_app()
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.endpoint.__module__.startswith("magister_api")
    ]


def _route_keys(route: APIRoute) -> list[tuple[str, str]]:
    return [(route.path, method) for method in sorted(route.methods or ())]


def _module_of_route() -> dict[tuple[str, frozenset[str]], str]:
    """Map each mounted (path, methods) to the id of the module that owns it.

    Modules are mounted without an extra prefix, so a router's own route path
    equals the app route path; prefixes are distinct across modules, so no key
    is claimed by two modules.
    """
    owner: dict[tuple[str, frozenset[str]], str] = {}
    for module in enabled_modules():
        for router in module.routers:
            for route in router.routes:
                if isinstance(route, APIRoute):
                    owner[(route.path, frozenset(route.methods or ()))] = module.id
    return owner


def test_registry_ids_match_catalog_ids() -> None:
    # Every mounted module must have catalog policy metadata (so it can be
    # toggled + guarded), and every catalog entry must be a real mounted module.
    registry_ids = {m.id for m in enabled_modules()}
    catalog_ids = set(catalog.module_ids())
    assert registry_ids == catalog_ids


def test_every_own_route_is_authenticated_or_explicitly_public() -> None:
    offenders: list[tuple[str, str]] = []
    for route in _own_routes():
        markers = set(_dependant_callables(route.dependant))
        for key in _route_keys(route):
            if key in PUBLIC_ROUTES:
                continue
            if _AUTH_MARKER not in markers:
                offenders.append(key)
    assert offenders == [], f"unauthenticated routes not on the public allowlist: {offenders}"


def test_public_allowlist_has_no_stale_entries() -> None:
    # A public route that gained auth (or was removed) must be dropped from the
    # allowlist, so the list keeps meaning "these are deliberately open".
    open_routes: set[tuple[str, str]] = set()
    live_routes: set[tuple[str, str]] = set()
    for route in _own_routes():
        markers = set(_dependant_callables(route.dependant))
        for key in _route_keys(route):
            live_routes.add(key)
            if _AUTH_MARKER not in markers:
                open_routes.add(key)
    stale = PUBLIC_ROUTES - open_routes
    assert stale == set(), f"allowlist entries that are no longer public (or gone): {stale}"
    assert PUBLIC_ROUTES <= live_routes


def test_toggleable_module_routes_are_guarded() -> None:
    owner = _module_of_route()
    missing_guard: list[str] = []
    unexpected_guard: list[str] = []
    for route in _own_routes():
        module_id = owner.get((route.path, frozenset(route.methods or ())))
        if module_id is None:
            continue  # /healthz and other app-level routes own no module
        meta = catalog.get_meta(module_id)
        assert meta is not None, f"{module_id} has no catalog meta"
        has_guard = _GUARD_MARKER in set(_dependant_callables(route.dependant))
        if meta.toggleable and not has_guard:
            missing_guard.append(f"{module_id}:{route.path}")
        if not meta.toggleable and has_guard:
            unexpected_guard.append(f"{module_id}:{route.path}")
    assert missing_guard == [], f"toggleable-module routes without request guard: {missing_guard}"
    assert unexpected_guard == [], f"non-toggleable routes carry a guard: {unexpected_guard}"
