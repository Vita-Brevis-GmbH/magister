"""CSRF token issue/verify."""

from __future__ import annotations

from magister_api.auth.csrf import issue_csrf_token, verify_csrf_token
from magister_api.config import Settings


def _settings() -> Settings:
    return Settings(
        audit_key="k",  # type: ignore[arg-type]
        session_secret="s",  # type: ignore[arg-type]
        csrf_secret="csrf-test-secret",  # type: ignore[arg-type]
    )


class TestCsrfToken:
    def test_round_trip(self) -> None:
        s = _settings()
        sid = "session-abc"
        tok = issue_csrf_token(sid, s)
        assert verify_csrf_token(tok, sid, s) is True

    def test_rejects_other_session(self) -> None:
        s = _settings()
        tok = issue_csrf_token("session-a", s)
        assert verify_csrf_token(tok, "session-b", s) is False

    def test_rejects_tampered_mac(self) -> None:
        s = _settings()
        tok = issue_csrf_token("session-a", s)
        nonce, _mac = tok.split(".", 1)
        bad = f"{nonce}.deadbeef"
        assert verify_csrf_token(bad, "session-a", s) is False

    def test_rejects_malformed(self) -> None:
        s = _settings()
        assert verify_csrf_token("no-dot", "session-a", s) is False

    def test_two_tokens_for_same_session_differ(self) -> None:
        s = _settings()
        a = issue_csrf_token("session-a", s)
        b = issue_csrf_token("session-a", s)
        assert a != b
