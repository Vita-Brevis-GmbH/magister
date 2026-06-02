from datetime import UTC, datetime, timedelta

import pytest

from cockpit_api.auth import hash_token
from cockpit_api.models import ServiceToken


def test_hash_token_deterministic() -> None:
    a = hash_token("foo")
    b = hash_token("foo")
    c = hash_token("bar")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex


def test_service_token_expiry_logic() -> None:
    """ServiceToken row knows when it expires."""
    row = ServiceToken(
        token_hash="x" * 64,
        description="test",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked=False,
    )
    assert row.expires_at > datetime.now(UTC)
    assert not row.revoked


@pytest.mark.parametrize(
    ("days_offset", "expected_valid"),
    [(1, True), (-1, False)],
)
def test_service_token_validity(days_offset: int, expected_valid: bool) -> None:
    row = ServiceToken(
        token_hash="x" * 64,
        description="test",
        expires_at=datetime.now(UTC) + timedelta(days=days_offset),
        revoked=False,
    )
    is_valid = not row.revoked and row.expires_at > datetime.now(UTC)
    assert is_valid is expected_valid
