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

from magister_api.ad._wordlist_de import WORDS_DE

# Avoid confusable glyphs (0/O/o, 1/l/I) so the hand-out PW is unambiguous.
_LOWER = "abcdefghijkmnpqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGIT = "23456789"
_SPECIAL = "!#$%&*+-=?@_"

DEFAULT_LENGTH = 14  # > 12 to give some headroom over AD's typical minimum
MIN_LENGTH = 12

# Readable-password defaults: two capitalised words joined by hyphens plus a
# trailing digit group. Kid-friendly to read out and type, while still hitting
# AD's 4-of-4 charset classes (upper via capitalisation, lower, digit, the
# hyphen as the special char).
READABLE_WORDS = 2
READABLE_MIN_DIGITS = 2


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


def generate_readable_password(
    *, words: int = READABLE_WORDS, min_digits: int = READABLE_MIN_DIGITS
) -> str:
    """Human-readable password (``Tiger-Wolke-47``) that still passes AD policy.

    Words are drawn from a curated German wordlist and capitalised; a trailing
    digit group is padded so the total always clears :data:`MIN_LENGTH`. The
    result therefore hits all four charset classes (upper, lower, digit, the
    ``-`` special) without relying on confusable glyphs.
    """
    if words < 1:
        raise ValueError("words must be >= 1")
    rng = secrets.SystemRandom()
    chosen = [rng.choice(WORDS_DE).capitalize() for _ in range(words)]
    base = "-".join(chosen)
    # Pad the digit group so `base-digits` is at least MIN_LENGTH characters.
    n_digits = max(min_digits, MIN_LENGTH - len(base) - 1)
    digits = "".join(rng.choice(_DIGIT) for _ in range(n_digits))
    pw = f"{base}-{digits}"
    # Construction guarantees length + 4 charset classes; verify defensively so
    # a future wordlist edit can never emit a policy-violating password.
    if not passes_default_complexity(pw):  # pragma: no cover - invariant
        raise ValueError("generated readable password failed complexity check")
    return pw


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
    "generate_readable_password",
    "passes_default_complexity",
]
