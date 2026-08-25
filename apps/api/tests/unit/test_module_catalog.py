"""M6 #5: the pure module-catalog policy + effective enablement (granular)."""

from __future__ import annotations

from magister_api.modules import catalog


def test_platform_is_always_on() -> None:
    for profile in ("school", "company", "neutral"):
        assert "platform" in catalog.effective_enabled_ids(profile, {})
    # An explicit False cannot disable the non-toggleable platform base.
    assert "platform" in catalog.effective_enabled_ids("neutral", {"platform": False})


def test_school_profile_defaults() -> None:
    enabled = set(catalog.effective_enabled_ids("school", {}))
    assert {"platform", "classes", "letters", "imports", "reports", "devices"} <= enabled
    assert "departments" not in enabled
    assert catalog.dependency_violations(enabled) == []


def test_company_profile_defaults() -> None:
    enabled = set(catalog.effective_enabled_ids("company", {}))
    # imports is on in both editions (company_users provisioning, #7).
    assert {"platform", "departments", "reports", "devices", "imports"} <= enabled
    # School superstructure (classes + its letters) is off in the company profile.
    assert enabled.isdisjoint({"classes", "letters"})
    assert catalog.dependency_violations(enabled) == []


def test_neutral_profile_is_minimal() -> None:
    enabled = set(catalog.effective_enabled_ids("neutral", {}))
    assert enabled == {"platform"}


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


def test_letters_requires_classes() -> None:
    meta = catalog.get_meta("letters")
    assert meta is not None
    assert "classes" in meta.depends_on
    # letters on but classes off is a violation.
    assert catalog.dependency_violations({"platform", "letters"}) == [("letters", "classes")]


def test_known_profiles_and_ids() -> None:
    assert catalog.DEFAULT_PROFILE in catalog.KNOWN_PROFILES
    assert set(catalog.module_ids()) == {
        "platform",
        "classes",
        "letters",
        "imports",
        "departments",
        "reports",
        "devices",
    }
