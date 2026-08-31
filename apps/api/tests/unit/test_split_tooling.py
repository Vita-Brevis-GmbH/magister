"""Split-plan Phase 1 (B) + observability (A): routing/overlay generator and
the per-container runtime snapshot.

All DB-free. The routing generator and the disjointness invariant are exercised
straight off the real module registry, so a new module with an overlapping path
prefix (which would make ``/api/<prefix>*`` ambiguous between containers) fails
here rather than in production.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from magister_api.config import Settings
from magister_api.modules.registry import module_path_prefixes
from magister_api.observability import runtime_snapshot

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_gen_split() -> ModuleType:
    path = _REPO_ROOT / "scripts" / "gen_split.py"
    spec = importlib.util.spec_from_file_location("gen_split", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen_split = _load_gen_split()


# --- registry invariant: disjoint prefixes are what makes path-routing sound ---


def test_feature_prefixes_are_disjoint_and_never_shadow_platform() -> None:
    prefixes = module_path_prefixes()
    platform = set(prefixes["platform"])
    assert platform, "platform must own at least one prefix (auth/me/...)"

    seen: dict[str, str] = {}
    for module_id, module_prefixes in prefixes.items():
        if module_id == "platform":
            continue
        for prefix in module_prefixes:
            # A feature prefix that collides with platform can never be routed to
            # its own container — platform is the catch-all base in every image.
            assert prefix not in platform, f"{module_id} prefix {prefix} shadows platform"
            # Two feature modules sharing a prefix would route /api/<prefix>* to
            # two containers at once — reject it here.
            assert prefix not in seen, (
                f"{module_id} and {seen[prefix]} both claim {prefix}; prefixes must be disjoint"
            )
            seen[prefix] = module_id


# --- A: per-container runtime snapshot ------------------------------------------


def test_runtime_snapshot_monolith_defaults() -> None:
    snap = runtime_snapshot(Settings())
    # Empty container_modules == the single-container monolith: every module,
    # platform included.
    assert "platform" in snap["modules"]
    assert "reports" in snap["modules"]
    # Default container owns the AD read loop.
    assert snap["scheduler_owner"] is True
    # RSS is measured from the live process, so it is always positive.
    assert snap["rss_mb"] > 0
    assert isinstance(snap["db_pool"], dict)


def test_runtime_snapshot_split_container() -> None:
    snap = runtime_snapshot(Settings(container_modules=["reports"], run_scheduler=False))
    assert set(snap["modules"]) == {"platform", "reports"}
    assert snap["scheduler_owner"] is False


# --- B: spec parsing -------------------------------------------------------------


def test_parse_spec_single_and_multi() -> None:
    assert gen_split.parse_spec(["reports=reports"]) == {"reports": ["reports"]}
    assert gen_split.parse_spec(["docs=imports,templates"]) == {"docs": ["imports", "templates"]}


@pytest.mark.parametrize("bad", ["reports", "=reports", "reports=", "reports= , "])
def test_parse_spec_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        gen_split.parse_spec([bad])


# --- B: Caddy routing ------------------------------------------------------------


def test_render_caddy_routes_targets_generated_upstream() -> None:
    out = gen_split.render_caddy_routes({"reports": ["reports"]})
    # Match exact + subtree, and strip only /api (not /api/reports) so the
    # backend still sees its /reports mount.
    assert "path /api/reports /api/reports/*" in out
    assert "uri strip_prefix /api" in out
    assert "reverse_proxy magister-api-reports:8000" in out
    # The ordering hint matters: these must sit before the generic /api/* block.
    assert "insert BEFORE" in out.splitlines()[0]


def test_render_caddy_routes_emits_all_module_prefixes() -> None:
    # departments serves two disjoint prefixes (/departments and /company); both
    # route to the same container via a single handle block.
    out = gen_split.render_caddy_routes({"abt": ["departments"]})
    assert "/api/departments /api/departments/*" in out
    assert "/api/company /api/company/*" in out
    # One handle block per container, so exactly one upstream, one strip.
    assert out.count("reverse_proxy magister-api-abt:8000") == 1
    assert out.count("uri strip_prefix /api") == 1


def test_render_caddy_rejects_platform() -> None:
    with pytest.raises(ValueError):
        gen_split.render_caddy_routes({"base": ["platform"]})


def test_render_caddy_rejects_unknown_module() -> None:
    with pytest.raises(ValueError):
        gen_split.render_caddy_routes({"x": ["nope"]})


# --- B: Compose overlay ----------------------------------------------------------


def test_render_compose_overlay_shape() -> None:
    out = gen_split.render_compose_overlay({"reports": ["reports"]})
    assert "magister-api-reports:" in out
    assert 'MAGISTER_CONTAINER_MODULES: "reports"' in out
    # A split container must never open a second scheduler or run migrations.
    assert 'MAGISTER_RUN_SCHEDULER: "0"' in out
    assert 'MAGISTER_SKIP_MIGRATIONS: "1"' in out


def test_render_compose_overlay_joins_multi_module() -> None:
    out = gen_split.render_compose_overlay({"docs": ["imports", "templates"]})
    assert 'MAGISTER_CONTAINER_MODULES: "imports,templates"' in out


def test_render_compose_overlay_validates_before_emitting() -> None:
    with pytest.raises(ValueError):
        gen_split.render_compose_overlay({"base": ["platform"]})
