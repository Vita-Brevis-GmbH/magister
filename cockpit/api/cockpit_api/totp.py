"""RFC-6238 TOTP helpers für die Konsolen-Anmeldung (ADR-0020 D2).

**Dieselbe Datei wie `magister_api/auth/totp.py`, absichtlich kopiert.** Die
Konsole hängt nicht von `magister_api` ab, und sie soll es nicht: sie läuft als
eigener Dienst, oft auf einer anderen Maschine (ADR-0013). Ein gemeinsames
Paket nur für hundert Zeilen Politik wäre ein dritter Ort, der bei jeder
Änderung mitgebaut werden muss.

Damit die Kopien nicht auseinanderlaufen, vergleicht ein Test die Werte, auf
die es ankommt (`tests/test_console_auth.py`). Das ist dieselbe Bauart wie bei
`POLICY_KEYS` und dem Assertion-Präfix.

Dünn gehalten: :mod:`pyotp` macht die RFC-Arbeit, hier stehen die Entscheide
darum — Fenster, Schrittbuchhaltung, Form der Wiederherstellungscodes, die
Provisioning-URI und ihr QR-Bild.

Nichts hier berührt die Datenbank oder protokolliert einen Code.
"""

from __future__ import annotations

import secrets
import time

import pyotp
import segno

#: Digits and period are the interoperable defaults every authenticator app
#: assumes; changing them silently breaks Google Authenticator and friends.
DIGITS = 6
PERIOD = 30

#: Accepted drift, in steps, either side of "now". One step (±30 s) covers a
#: clock that is a little off without widening the window a code stays usable.
DRIFT_STEPS = 1

#: Ten single-use codes, shown once at enrolment.
RECOVERY_CODE_COUNT = 10
#: Two groups of four from an unambiguous alphabet (no 0/O, 1/I/L) so a code
#: read off paper over the phone does not get mistyped.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_RECOVERY_GROUP_LEN = 4


def new_secret() -> str:
    """A fresh base32 shared secret (160 bit, the RFC-4226 recommendation)."""
    return pyotp.random_base32()


def current_step(now: float | None = None) -> int:
    """The 30-second time step *now* falls into."""
    return int((time.time() if now is None else now) // PERIOD)


def verify_code(secret: str, code: str, *, last_step: int | None) -> int | None:
    """Verify *code* against *secret* and return the step it matched.

    Returns ``None`` when the code is wrong, malformed, or replays a step that
    was already accepted (``last_step``). Returning the step — rather than a
    bool — is what lets the caller persist it and make every code single-use.
    """
    cleaned = code.strip().replace(" ", "")
    # ``isascii()`` matters: ``str.isdigit()`` is True for full-width digits
    # (U+FF10 FULLWIDTH DIGIT ZERO und Geschwister), und ``compare_digest``
    # wirft bei Nicht-ASCII einen TypeError — aus einem missgebildeten Code
    # würde damit ein 500 statt eines „ungültig".
    #
    # Das Zeichen steht hier als Codepunkt und nicht als Zeichen: die
    # ruff-Regel RUF003 der Konsole weist ein solches Zeichen im Kommentar ab,
    # und sie hat recht — in der Datenebene steht es im Klartext, weil dort
    # die Regel nicht aktiv ist.
    if not (cleaned.isascii() and cleaned.isdigit()) or len(cleaned) != DIGITS:
        return None
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD)
    now = current_step()
    for offset in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        step = now + offset
        if last_step is not None and step <= last_step:
            # Already used (or older than the last accepted one): no replay.
            continue
        if secrets.compare_digest(totp.at(step * PERIOD), cleaned):
            return step
    return None


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    """The ``otpauth://`` URI an authenticator app scans."""
    return pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD).provisioning_uri(
        name=account, issuer_name=issuer
    )


def qr_data_uri(uri: str) -> str:
    """Render *uri* as an SVG ``data:`` URI, ready for an ``<img src=…>``.

    Server-side on purpose: the CSP already allows ``img-src 'self' data:`` and
    no external script, so a bundled JS QR library or a CDN would need either a
    new SPA dependency or a CSP change.
    """
    return segno.make(uri, error="m").svg_data_uri(scale=1)


def new_recovery_codes() -> list[str]:
    """Ten fresh recovery codes in ``XXXX-XXXX`` form."""
    return [
        "-".join(
            "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_GROUP_LEN))
            for _ in range(2)
        )
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def normalize_recovery_code(code: str) -> str:
    """Upper-case, strip spaces, keep the dash — so paper input is forgiving."""
    return code.strip().upper().replace(" ", "")


__all__ = [
    "DIGITS",
    "DRIFT_STEPS",
    "PERIOD",
    "RECOVERY_CODE_COUNT",
    "current_step",
    "new_recovery_codes",
    "new_secret",
    "normalize_recovery_code",
    "provisioning_uri",
    "qr_data_uri",
    "verify_code",
]
