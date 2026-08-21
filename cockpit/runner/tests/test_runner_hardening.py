"""M4.3 / hardening-audit M-02: last_error tokens must be whitelist-safe.

The cockpit ``last_error`` column is operator-visible, so the runner must only
ever persist a stable, non-sensitive token there — never raw stdout/stderr or a
formatted exception, which can carry paths, URLs or env values.
"""

from __future__ import annotations

import re
from uuid import UUID, uuid4

import pytest

import cockpit_runner.executor as executor
import cockpit_runner.main as runner_main
from cockpit_runner.cockpit_client import ClaimedRequest
from cockpit_runner.executor import UpdateFailed


def _req() -> ClaimedRequest:
    return ClaimedRequest(
        id=uuid4(),
        instance_slug="schule-x",
        instance_base_url="https://schule-x.example.ch",
        instance_channel="stable",
        target_version="0.4.0",
    )


class _FakeClient:
    """Minimal CockpitClient stand-in capturing the fail/complete calls."""

    def __init__(self, req: ClaimedRequest | None) -> None:
        self._req = req
        self.failed_with: str | None = None
        self.completed = False

    def claim_next(self) -> ClaimedRequest | None:
        req, self._req = self._req, None
        return req

    def fail(self, request_id: UUID, error: str) -> None:
        self.failed_with = error

    def complete(self, request_id: UUID) -> None:
        self.completed = True


def test_run_step_token_is_whitelist_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    # A failed step surfaces as "<step>_failed (rc=N)" — the step name must not
    # contain spaces, and no stderr may leak into the persisted token.
    monkeypatch.setattr(
        executor, "_ssh", lambda host, command: (1, "stdout", "stderr with /secret/path")
    )
    with pytest.raises(UpdateFailed) as exc:
        executor._run("host", "some command", step="docker_pull")
    msg = str(exc.value)
    token = msg.split(" ", 1)[0]
    assert re.fullmatch(r"[a-z0-9_]+_failed", token), token
    assert "secret" not in msg


def test_unexpected_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    # An unexpected (non-UpdateFailed) exception must be reduced to a fixed
    # token; str(e) — which here carries a secret path — must not reach cockpit.
    def _boom(req: ClaimedRequest) -> None:
        raise ValueError("connect failed to /etc/magister/secret.env")

    monkeypatch.setattr(runner_main, "execute_update", _boom)
    client = _FakeClient(_req())
    assert runner_main._process_once(client) is True
    assert client.failed_with == "unexpected_error"
    assert client.completed is False


def test_update_failed_token_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(req: ClaimedRequest) -> None:
        raise UpdateFailed("smoke_test_version_mismatch")

    monkeypatch.setattr(runner_main, "execute_update", _fail)
    client = _FakeClient(_req())
    assert runner_main._process_once(client) is True
    assert client.failed_with == "smoke_test_version_mismatch"
    assert client.completed is False


def test_success_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_main, "execute_update", lambda req: None)
    client = _FakeClient(_req())
    assert runner_main._process_once(client) is True
    assert client.failed_with is None
    assert client.completed is True
