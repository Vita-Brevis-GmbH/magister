"""Gesundheit des AD-Abgleichs: inkrementell im Intervall, vollständig im Tagestakt.

Früher wurde der vollständige Abgleich am Intervall gemessen — jede Instanz
mit tadellosem Abgleich stand nach 45 Minuten auf "warning".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from magister_api.services.stack_health import CRITICAL, OK, WARNING, _sync_check


def _settings(interval: int = 15, full_hours: int = 24) -> Any:
    return SimpleNamespace(ad_sync_interval_minutes=interval, ad_full_sync_hours=full_hours)


def _ago(**kw: float) -> datetime:
    return datetime.now(UTC) - timedelta(**kw)


def test_incremental_runs_keep_it_green_although_the_full_one_is_hours_old() -> None:
    check = _sync_check(True, _ago(hours=21), _settings(), _ago(minutes=10))
    assert check.status == OK, check.detail


def test_missed_incremental_runs_warn() -> None:
    check = _sync_check(True, _ago(hours=2), _settings(), _ago(minutes=50))
    assert check.status == WARNING
    assert "Intervall 15" in check.detail


def test_an_overdue_full_sync_warns() -> None:
    check = _sync_check(True, _ago(hours=26), _settings(), _ago(minutes=5))
    assert check.status == WARNING
    assert "vollständig" in check.detail


def test_a_day_without_any_run_is_critical() -> None:
    check = _sync_check(True, _ago(hours=30), _settings(), _ago(hours=25))
    assert check.status == CRITICAL


def test_never_ran_is_a_warning() -> None:
    assert _sync_check(False, None, _settings()).status == WARNING
    assert _sync_check(True, None, _settings(), _ago(minutes=1)).status == WARNING
