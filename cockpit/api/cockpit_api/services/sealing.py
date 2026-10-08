"""Geheimnisse versiegeln, die die Konsole selbst nicht öffnen kann (ADR-0024 D3).

ADR-0017 D2 hält fest: in der Konsole liegen keine Kundengeheimnisse. Dabei
bleibt es — gelesen als „keine, die sie lesen kann". Das Entra-Client-Secret
eines Kunden wird hier mit dem **öffentlichen** Schlüssel seiner Datenebene
versiegelt; gespeichert wird nur das Chiffrat. Öffnen kann es nur die
Datenebene, die den privaten Schlüssel aus dem Kundenschlüssel ableitet.

Verfahren (versiegelte Box, wie libsodium `crypto_box_seal`, aus den
Bausteinen von `cryptography`):

* frisches X25519-Schlüsselpaar je Versiegelung,
* gemeinsamer Wert mit dem öffentlichen Schlüssel des Empfängers,
* HKDF-SHA256 (Salz: beide öffentlichen Schlüssel) → 32 Byte,
* ChaCha20-Poly1305 mit zufälliger Nonce; die zusätzlichen Daten binden das
  Chiffrat an **Kunde und Name** — ein Chiffrat für `oidc_client_secret` von
  Kunde A lässt sich weder bei Kunde B noch als anderes Feld einsetzen.

Format: ``v1.`` + base64url(ephemeral_pub ‖ nonce ‖ ciphertext).

Dieselbe Rechnung steht in ``apps/api/magister_api/tenancy/sealing.py`` (dort
das Öffnen). ``tests/test_sealing_parity.py`` versiegelt hier und öffnet dort.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION = "v1"
INFO = b"magister-sealed-secret-v1"

#: Was sich versiegeln lässt. Eine Allowlist wie bei den Einstellungen: ein
#: neues Geheimnis ist eine bewusste Entscheidung, kein freies Feld.
SEALABLE: frozenset[str] = frozenset({"oidc_client_secret", "ninja_client_secret"})

#: Versiegelt, aber nicht als Einstellung gespeichert: reist in einem
#: Wartungsauftrag und wird einmal angewandt (lokales Admin-Konto). Dieselbe
#: Liste wie in der Datenebene.
ONE_TIME_SEALABLE: frozenset[str] = frozenset({"local_admin_password"})


class SealingError(ValueError):
    """Versiegeln nicht möglich (kein oder ungültiger Schlüssel)."""


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def key_id(public_key_b64: str) -> str:
    """Fingerabdruck eines öffentlichen Schlüssels (16 Hex-Zeichen)."""
    return hashlib.sha256(_b64d(public_key_b64)).hexdigest()[:16]


def _aad(tenant_ref: str, name: str) -> bytes:
    return f"{VERSION}|{tenant_ref}|{name}".encode()


def seal(public_key_b64: str, plaintext: str, *, tenant_ref: str, name: str) -> str:
    """Versiegeln für den Empfänger mit ``public_key_b64``."""
    try:
        recipient = X25519PublicKey.from_public_bytes(_b64d(public_key_b64))
    except ValueError as exc:
        raise SealingError("Der gemeldete öffentliche Schlüssel ist ungültig.") from exc
    ephemeral = X25519PrivateKey.generate()
    eph_pub = ephemeral.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    rec_pub = recipient.public_bytes(Encoding.Raw, PublicFormat.Raw)
    shared = ephemeral.exchange(recipient)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=eph_pub + rec_pub, info=INFO).derive(
        shared
    )
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext.encode("utf-8"), _aad(tenant_ref, name))
    return f"{VERSION}.{_b64e(eph_pub + nonce + ct)}"


__all__ = ["ONE_TIME_SEALABLE", "SEALABLE", "SealingError", "key_id", "seal"]
