"""Argon2id helper round-trip + tamper-resistance."""

from __future__ import annotations

from magister_api.auth.passwords import hash_password, needs_rehash, verify_password


def test_hash_then_verify_roundtrips() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("not the same password", h) is False


def test_verify_returns_false_on_garbage_hash() -> None:
    assert verify_password("anything", "definitely-not-an-argon2-hash") is False


def test_needs_rehash_is_false_for_fresh_hash() -> None:
    h = hash_password("x" * 32)
    assert needs_rehash(h) is False
