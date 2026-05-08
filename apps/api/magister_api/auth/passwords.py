"""Argon2id password hashing for the local-admin account.

Why argon2id (not bcrypt):
- memory-hard, OWASP-recommended;
- no 72-byte truncation gotcha;
- the ``needs_rehash`` helper lets us bump parameters in a future migration
  without invalidating existing hashes.

Parameters follow the OWASP minimum baseline as of 2024-2025: t=3, m=64 MiB,
p=4. They take ~50 ms on a typical server-grade CPU, which is the right
order of magnitude for an interactive login.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain: str) -> str:
    """Return an argon2id encoded hash of *plain*."""
    return _HASHER.hash(plain)


def verify_password(plain: str, hash_: str) -> bool:
    """Return True iff *plain* matches *hash_*; False on mismatch or malformed hash."""
    try:
        return _HASHER.verify(hash_, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hash_: str) -> bool:
    """Return True if *hash_* should be re-computed (parameters bumped)."""
    return _HASHER.check_needs_rehash(hash_)


__all__ = ["hash_password", "verify_password", "needs_rehash"]
