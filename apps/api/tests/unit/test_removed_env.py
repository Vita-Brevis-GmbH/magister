"""Removed security settings must not pass silently (ADR-0015 D3).

``Settings`` uses ``extra="ignore"``, so a leftover ``MAGISTER_AD_LOGIN_*`` in a
deployment's env would simply be dropped — and an operator would keep believing
a login path exists that no longer does. The startup check turns that into a
loud failure (switched on) or a loud log line (stale but off).
"""

from __future__ import annotations

import logging

import pytest

from magister_api.config import REMOVED_ENV_VARS, Settings


def test_removed_vars_are_documented_with_a_reason() -> None:
    assert "MAGISTER_AD_LOGIN_ENABLED" in REMOVED_ENV_VARS
    assert "MAGISTER_AD_LOGIN_GROUP" in REMOVED_ENV_VARS
    for name, reason in REMOVED_ENV_VARS.items():
        assert reason.strip(), f"{name} has no operator-facing reason"


def test_clean_env_passes() -> None:
    Settings.reject_removed_env({"MAGISTER_AUDIT_KEY": "x"})


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_switched_on_aborts_the_start(value: str) -> None:
    with pytest.raises(RuntimeError, match="MAGISTER_AD_LOGIN_ENABLED"):
        Settings.reject_removed_env({"MAGISTER_AD_LOGIN_ENABLED": value})


def test_group_alone_aborts_when_truthy() -> None:
    # A group name is not a boolean, so it is treated as stale config, not as
    # "switched on" — it warns rather than aborting.
    with pytest.raises(RuntimeError, match="MAGISTER_AD_LOGIN_ENABLED"):
        Settings.reject_removed_env(
            {"MAGISTER_AD_LOGIN_ENABLED": "yes", "MAGISTER_AD_LOGIN_GROUP": "CN=Magister"}
        )


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_switched_off_only_warns(value: str, caplog: pytest.LogCaptureFixture) -> None:
    # Blocking an upgrade over a stale ``=false`` would be friction without any
    # security gain — but it must still be visible.
    with caplog.at_level(logging.WARNING, logger="magister_api.config"):
        Settings.reject_removed_env({"MAGISTER_AD_LOGIN_ENABLED": value})
    assert any("MAGISTER_AD_LOGIN_ENABLED" in r.getMessage() for r in caplog.records)


def test_empty_value_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="magister_api.config"):
        Settings.reject_removed_env({"MAGISTER_AD_LOGIN_ENABLED": "  "})
    assert caplog.records == []
