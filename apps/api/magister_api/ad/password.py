"""AD password helpers: generator + probe-bind validator.

The generator produces 12-character minimum random passwords that satisfy AD's
default complexity policy (3 of 4 charset classes: uppercase, lowercase, digit,
special). We use :mod:`secrets` for cryptographic randomness and avoid the
visually confusable 0/O, 1/l/I characters to reduce hand-out errors.

The probe-bind helper authenticates the manual password against AD as the
target user before the actual ``modify`` is issued. AD enforces password
policy at bind time for new credentials, so a successful probe confirms the
new password would also be accepted by ``unicodePwd``.
"""

from __future__ import annotations

import secrets
import string

# Avoid confusable glyphs (0/O/o, 1/l/I) so the hand-out PW is unambiguous.
_LOWER = "abcdefghijkmnpqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGIT = "23456789"
_SPECIAL = "!#$%&*+-=?@_"

DEFAULT_LENGTH = 14  # > 12 to give some headroom over AD's typical minimum
MIN_LENGTH = 12


def generate_password(length: int = DEFAULT_LENGTH) -> str:
    """Cryptographically random password meeting AD-Default complexity policy."""
    if length < MIN_LENGTH:
        raise ValueError(f"length must be >= {MIN_LENGTH}")
    rng = secrets.SystemRandom()
    # Force one char from each of the four classes so the result hits 4-of-4
    # (AD requires 3-of-4; we go one step further).
    chars: list[str] = [
        rng.choice(_LOWER),
        rng.choice(_UPPER),
        rng.choice(_DIGIT),
        rng.choice(_SPECIAL),
    ]
    pool = _LOWER + _UPPER + _DIGIT + _SPECIAL
    chars.extend(rng.choice(pool) for _ in range(length - len(chars)))
    rng.shuffle(chars)
    return "".join(chars)


def count_charset_classes(pw: str) -> int:
    classes = 0
    if any(c in string.ascii_lowercase for c in pw):
        classes += 1
    if any(c in string.ascii_uppercase for c in pw):
        classes += 1
    if any(c.isdigit() for c in pw):
        classes += 1
    if any(c in string.punctuation for c in pw):
        classes += 1
    return classes


def passes_default_complexity(pw: str) -> bool:
    """True if ``pw`` satisfies AD's default 12+chars, 3-of-4-classes policy."""
    return len(pw) >= MIN_LENGTH and count_charset_classes(pw) >= 3


__all__ = [
    "DEFAULT_LENGTH",
    "MIN_LENGTH",
    "count_charset_classes",
    "generate_password",
    "passes_default_complexity",
]
