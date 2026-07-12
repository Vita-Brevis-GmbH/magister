"""Sync-failure reason classification.

The bind can succeed (connection test green) while the sync still fails because
it searches a subtree — these map the internal AdUnavailableError markers to the
specific, translatable reason the operator needs.
"""

from __future__ import annotations

from magister_api.ad.errors import (
    SYNC_REASON_BIND_FAILED,
    SYNC_REASON_CONFIG,
    SYNC_REASON_SEARCH_BASE_MISSING,
    SYNC_REASON_SEARCH_FAILED,
    SYNC_REASON_UNAVAILABLE,
    AdUnavailableError,
    classify_sync_failure,
)


def _r(msg: str) -> str:
    return classify_sync_failure(AdUnavailableError(msg))


def test_missing_search_base() -> None:
    assert _r("MAGISTER_AD_USERS_SEARCH_BASE is not configured") == SYNC_REASON_SEARCH_BASE_MISSING


def test_search_failed() -> None:
    assert _r("ldap_search_failed") == SYNC_REASON_SEARCH_FAILED
    assert _r("ldap_computer_search_failed") == SYNC_REASON_SEARCH_FAILED


def test_bind_failed() -> None:
    assert _r("ldap_bind_failed") == SYNC_REASON_BIND_FAILED


def test_config() -> None:
    assert _r("MAGISTER_AD_DCS is empty") == SYNC_REASON_CONFIG
    assert _r("MAGISTER_AD_BIND_DN / _BIND_PASSWORD must be set") == SYNC_REASON_CONFIG


def test_unknown_falls_back_to_unavailable() -> None:
    assert _r("something else entirely") == SYNC_REASON_UNAVAILABLE
