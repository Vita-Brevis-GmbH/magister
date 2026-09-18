"""M6 Phase 0: the module registry must preserve the historical route set.

Phase 0 is a pure refactor — grouping the routers into a ``platform`` and a
``school`` module and mounting them via the registry must not add, drop or
change any route, and every registered module's routes must actually be mounted.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from magister_api.main import create_app
from magister_api.modules.platform import OPERATOR_ROUTERS
from magister_api.modules.registry import ALL_MODULES, enabled_modules


def _app_route_keys() -> set[tuple[str, frozenset[str]]]:
    app = create_app()
    return {(r.path, frozenset(r.methods or ())) for r in app.routes if isinstance(r, APIRoute)}


def _route_keys(router: object) -> set[tuple[str, frozenset[str]]]:
    return {
        (r.path, frozenset(r.methods or ()))
        for r in getattr(router, "routes", [])
        if isinstance(r, APIRoute)
    }


def test_every_enabled_module_router_is_mounted() -> None:
    """Jeder registrierte Router ist gemountet — ausser den bedingten.

    Bedingt heisst: eine Fläche, die es nur unter einer Voraussetzung gibt.
    Bisher war das keine; seit ADR-0019 D3 hängt die Operator-Fläche an einem
    hinterlegten öffentlichen Schlüssel, und `create_app()` ohne Einstellungen
    hat keinen. Dieser Test hat den Unterschied zu Recht gemeldet.
    """
    mounted = _app_route_keys()
    conditional = {key for router in OPERATOR_ROUTERS for key in _route_keys(router)}
    for module in enabled_modules():
        for router in module.routers:
            for route in router.routes:
                if isinstance(route, APIRoute):
                    key = (route.path, frozenset(route.methods or ()))
                    if key in conditional:
                        continue
                    assert key in mounted, f"{module.id}: {route.path} {route.methods} not mounted"


def test_the_conditional_surface_is_absent_by_default() -> None:
    """Die Gegenprobe: ohne Schlüssel ist die Operator-Fläche **nicht da**.

    Nicht 403, gar nicht (ADR-0019 D3). Ohne diese Prüfung wäre die Ausnahme
    oben eine Erlaubnis, die Fläche versehentlich immer zu mounten.
    """
    mounted = _app_route_keys()
    for router in OPERATOR_ROUTERS:
        for key in _route_keys(router):
            assert key not in mounted, f"{key} sollte ohne Schlüssel nicht gemountet sein"


def test_the_conditional_surface_appears_with_a_key() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from magister_api.config import Settings

    pem = (
        ed25519.Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    app = create_app(
        Settings(
            audit_key="k" * 32,  # type: ignore[arg-type]
            session_secret="s" * 32,  # type: ignore[arg-type]
            csrf_secret="c" * 32,  # type: ignore[arg-type]
            operator_public_key=pem,
        )
    )
    mounted = {(r.path, frozenset(r.methods or ())) for r in app.routes if isinstance(r, APIRoute)}
    for router in OPERATOR_ROUTERS:
        for key in _route_keys(router):
            assert key in mounted, f"{key} fehlt, obwohl ein Schlüssel hinterlegt ist"


def test_router_count() -> None:
    # 34 routers total. M6 #5 + the platform carve (10-container split) were pure
    # redistribution at 32; the generic /users/{guid}/password-reset router
    # (company-user password reset) took it to 33, and the operator surface
    # (ADR-0019) to 34.
    total = sum(len(m.routers) for m in ALL_MODULES)
    assert total == 34


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
