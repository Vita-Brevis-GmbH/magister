"""The signed, stateless proof that a password was just verified."""

from __future__ import annotations

import time

import pytest
from pydantic import SecretStr

from magister_api.auth import login_challenge
from magister_api.config import Settings


def _settings(secret: str = "challenge-secret") -> Settings:
    return Settings(session_secret=SecretStr(secret))


class TestRoundTrip:
    def test_a_fresh_challenge_verifies_to_its_username(self) -> None:
        s = _settings()
        token = login_challenge.issue(username="admin", stage="totp", settings=s)
        assert login_challenge.verify(token, stage="totp", settings=s) == "admin"

    def test_two_challenges_differ(self) -> None:
        s = _settings()
        a = login_challenge.issue(username="admin", stage="totp", settings=s)
        b = login_challenge.issue(username="admin", stage="totp", settings=s)
        assert a != b  # a nonce is part of the body


class TestRejection:
    def test_wrong_stage_is_refused(self) -> None:
        """An enrolment challenge must not be redeemable at the TOTP step."""
        s = _settings()
        token = login_challenge.issue(username="admin", stage="enroll", settings=s)
        assert login_challenge.verify(token, stage="totp", settings=s) is None

    def test_another_secret_cannot_mint_one(self) -> None:
        token = login_challenge.issue(username="admin", stage="totp", settings=_settings("a"))
        assert login_challenge.verify(token, stage="totp", settings=_settings("b")) is None

    def test_expiry_is_enforced(self) -> None:
        s = _settings()
        token = login_challenge.issue(username="admin", stage="totp", settings=s)
        later = time.time() + login_challenge.CHALLENGE_TTL_SECONDS + 1
        assert login_challenge.verify(token, stage="totp", settings=s, now=later) is None

    def test_a_tampered_body_is_refused(self) -> None:
        s = _settings()
        token = login_challenge.issue(username="admin", stage="totp", settings=s)
        payload, mac = token.split(".", 1)
        assert login_challenge.verify(f"{payload}x.{mac}", stage="totp", settings=s) is None

    @pytest.mark.parametrize("bad", ["", ".", "no-dot", "a.b", "!!!.???"])
    def test_garbage_is_refused_without_raising(self, bad: str) -> None:
        assert login_challenge.verify(bad, stage="totp", settings=_settings()) is None

    def test_without_a_session_secret_nothing_can_be_issued_or_verified(self) -> None:
        empty = Settings(session_secret=SecretStr(""))
        with pytest.raises(RuntimeError, match="MAGISTER_SESSION_SECRET"):
            login_challenge.issue(username="admin", stage="totp", settings=empty)
        assert login_challenge.verify("a.b", stage="totp", settings=empty) is None
