"""Versiegelte Geheimnisse aus der Konsole öffnen (ADR-0024 D3).

Die Konsole versiegelt ein Geheimnis (Entra-Client-Secret) mit dem
öffentlichen Schlüssel dieser Datenebene und hält nur das Chiffrat. Hier wird
es geöffnet und, mit dem Kundenschlüssel verschlüsselt, ins Kundenschema
geschrieben — dort, wo es nach ADR-0017 D2 hingehört.

**Der private Schlüssel wird nicht gespeichert, sondern abgeleitet**: HKDF aus
dem Geheimnisschlüssel des Kunden (`MAGISTER_TENANT_SECRETS_KEY_<REF>` bzw.
dem Rückfall). Damit gibt es keinen zusätzlichen Schlüssel zu sichern, und
jeder Kunde hat seinen eigenen. Wird der Kundenschlüssel gedreht, ändert sich
das Schlüsselpaar; der Fingerabdruck in der Zustandsmeldung ändert sich mit,
und die Konsole zeigt das Geheimnis als neu zu setzen.

Die Gegenstelle (Versiegeln) steht in
``cockpit/api/cockpit_api/services/sealing.py``; ein Paritätstest dort
versiegelt mit jener Datei und öffnet mit dieser.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION = "v1"
INFO = b"magister-sealed-secret-v1"
_DERIVE_INFO = b"magister-sealed-secret-keypair-v1"

#: Dieselbe Allowlist wie in der Konsole. Was nicht hier steht, wird nicht
#: geöffnet — auch wenn die Konsole es schickt.
SEALABLE: frozenset[str] = frozenset({"oidc_client_secret", "ninja_client_secret"})


class UnsealError(ValueError):
    """Öffnen gescheitert. Die Meldung enthält nie Klartext oder Schlüssel."""


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def private_key(secrets_key: str) -> X25519PrivateKey:
    """Das Schlüsselpaar dieses Kunden, aus seinem Geheimnisschlüssel abgeleitet."""
    if not secrets_key:
        raise UnsealError("Kein Geheimnisschlüssel für diesen Kunden.")
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_DERIVE_INFO).derive(
        secrets_key.encode("utf-8")
    )
    return X25519PrivateKey.from_private_bytes(raw)


def public_key_b64(secrets_key: str) -> str:
    pub = private_key(secrets_key).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b64e(pub)


def key_id(public_key: str) -> str:
    return hashlib.sha256(_b64d(public_key)).hexdigest()[:16]


def unseal(secrets_key: str, sealed: str, *, tenant_ref: str, name: str) -> str:
    """Ein Chiffrat aus der Konsole öffnen."""
    if name not in SEALABLE:
        raise UnsealError(f"'{name}' ist kein versiegelbares Geheimnis.")
    version, _, body = sealed.partition(".")
    if version != VERSION or not body:
        raise UnsealError("Unbekanntes Format des versiegelten Geheimnisses.")
    try:
        blob = _b64d(body)
    except ValueError as exc:
        raise UnsealError("Das versiegelte Geheimnis ist nicht lesbar.") from exc
    if len(blob) < 32 + 12 + 16:
        raise UnsealError("Das versiegelte Geheimnis ist zu kurz.")
    eph_pub, nonce, ct = blob[:32], blob[32:44], blob[44:]
    priv = private_key(secrets_key)
    rec_pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    shared = priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=eph_pub + rec_pub, info=INFO).derive(
        shared
    )
    aad = f"{VERSION}|{tenant_ref}|{name}".encode()
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, ct, aad).decode("utf-8")
    except InvalidTag as exc:
        # Falscher Schlüssel (Kundenschlüssel gedreht), falscher Kunde oder
        # verändertes Chiffrat. Für den Betreiber derselbe Handgriff: neu setzen.
        raise UnsealError(
            "Das Geheimnis lässt sich mit dem Schlüssel dieses Kunden nicht öffnen — "
            "in der Konsole neu setzen."
        ) from exc


__all__ = ["SEALABLE", "UnsealError", "key_id", "private_key", "public_key_b64", "unseal"]
