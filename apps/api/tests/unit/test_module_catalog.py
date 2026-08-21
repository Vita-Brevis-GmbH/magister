"""M6 Phase 1: the pure module-catalog policy + effective enablement."""

from __future__ import annotations

from magister_api.modules import catalog


def test_platform_is_always_on() -> None:
    for profile in ("school", "company", "neutral"):
        assert "platform" in catalog.effective_enabled_ids(profile, {})
    # An explicit False cannot disable the non-toggleable platform base.
    assert "platform" in catalog.effective_enabled_ids("neutral", {"platform": False})


def test_school_default_follows_profile() -> None:
    assert "school" in catalog.effective_enabled_ids("school", {})
    assert "school" not in catalog.effective_enabled_ids("company", {})
    assert "school" not in catalog.effective_enabled_ids("neutral", {})


def test_company_default_follows_profile() -> None:
    assert "company" in catalog.effective_enabled_ids("company", {})
    assert "company" not in catalog.effective_enabled_ids("school", {})
    assert "company" not in catalog.effective_enabled_ids("neutral", {})


def test_school_and_company_can_coexist() -> None:
    # Mischbetrieb: a school instance that also switches the company module on.
    enabled = set(catalog.effective_enabled_ids("school", {"company": True}))
    assert {"platform", "school", "company"} <= enabled
    assert catalog.dependency_violations(enabled) == []


def test_override_wins_over_profile_default() -> None:
    # A school module can be switched on inside a company instance …
    assert "school" in catalog.effective_enabled_ids("company", {"school": True})
    # … and off inside a school instance.
    assert "school" not in catalog.effective_enabled_ids("school", {"school": False})


def test_dependencies_satisfied_for_defaults() -> None:
    enabled = set(catalog.effective_enabled_ids("school", {}))
    assert catalog.dependency_violations(enabled) == []


def test_dependency_violation_is_detected() -> None:
    assert catalog.dependency_violations({"school"}) == [("school", "platform")]


def test_known_profiles_and_ids() -> None:
    assert catalog.DEFAULT_PROFILE in catalog.KNOWN_PROFILES
    assert set(catalog.module_ids()) == {"platform", "school", "company"}
