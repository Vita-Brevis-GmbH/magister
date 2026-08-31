"""M6 #5: the pure module-catalog policy + effective enablement (granular)."""

from __future__ import annotations

from magister_api.modules import catalog

# The always-on base after the platform carve: none of these is toggleable, so
# they are enabled under every profile regardless of overrides.
BASE = {"platform", "ad", "users", "settings"}


def test_base_modules_are_always_on() -> None:
    for profile in ("school", "company", "neutral"):
        assert BASE <= set(catalog.effective_enabled_ids(profile, {}))
    # An explicit False cannot disable a non-toggleable base module.
    for base_id in BASE:
        assert base_id in catalog.effective_enabled_ids("neutral", {base_id: False})


def test_school_profile_defaults() -> None:
    enabled = set(catalog.effective_enabled_ids("school", {}))
    assert BASE | {"classes", "templates", "imports", "reports", "devices"} <= enabled
    assert "departments" not in enabled
    assert catalog.dependency_violations(enabled) == []


def test_company_profile_defaults() -> None:
    enabled = set(catalog.effective_enabled_ids("company", {}))
    # imports + templates are on in both editions (company_users provisioning #7,
    # Vorlagen useful for company letters).
    assert BASE | {"departments", "reports", "devices", "imports", "templates"} <= enabled
    # School superstructure (classes) is off in the company profile.
    assert "classes" not in enabled
    assert catalog.dependency_violations(enabled) == []


def test_neutral_profile_is_minimal() -> None:
    enabled = set(catalog.effective_enabled_ids("neutral", {}))
    assert enabled == BASE


def test_mischbetrieb_school_plus_departments() -> None:
    # A school that also switches the departments module on.
    enabled = set(catalog.effective_enabled_ids("school", {"departments": True}))
    assert {"classes", "departments"} <= enabled
    assert catalog.dependency_violations(enabled) == []


def test_override_wins_over_profile_default() -> None:
    # classes can be switched off inside a school instance …
    assert "classes" not in catalog.effective_enabled_ids("school", {"classes": False})
    # … and departments on inside a school instance.
    assert "departments" in catalog.effective_enabled_ids("school", {"departments": True})


def test_templates_depends_only_on_platform() -> None:
    meta = catalog.get_meta("templates")
    assert meta is not None
    assert meta.depends_on == ("platform",)
    # platform is always on, so an enabled templates never violates its dependency.
    assert catalog.dependency_violations({"platform", "templates"}) == []


def test_known_profiles_and_ids() -> None:
    assert catalog.DEFAULT_PROFILE in catalog.KNOWN_PROFILES
    assert set(catalog.module_ids()) == {
        "platform",
        "ad",
        "users",
        "settings",
        "templates",
        "classes",
        "imports",
        "departments",
        "reports",
        "devices",
    }
