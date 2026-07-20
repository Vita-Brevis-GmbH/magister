"""Web-server TLS certificate: parse/validate imports and materialize to disk.

Two jobs, no DB:

1. Accept an imported certificate — either a PEM cert chain + PEM private key,
   or a PKCS#12/PFX blob (+ optional password) — validate that the key matches
   the leaf certificate, and normalise both to PEM text for storage.
2. Materialize the *effective* certificate to a directory Caddy reads: when a
   custom cert is configured, write ``tls.pem``/``tls.key`` and a Caddy snippet
   pointing at them; otherwise write a snippet that falls back to Caddy's
   self-signed ``internal`` issuer and remove any stale key material.

The private key never appears in logs or audit payloads.
"""

from __future__ import annotations

import os

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

CERT_FILENAME = "tls.pem"
KEY_FILENAME = "tls.key"
SNIPPET_FILENAME = "tls.caddy"


class WebTlsError(ValueError):
    """Raised when an imported certificate/key is invalid or mismatched."""


def _public_bytes(key: object) -> bytes:
    return key.public_key().public_bytes(  # type: ignore[attr-defined]
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def normalize_pem(cert_pem: str, key_pem: str) -> tuple[str, str]:
    """Validate a PEM chain + private key and return them normalised.

    Ensures the chain parses, the key parses (unencrypted), and the private key
    matches the leaf certificate. Raises :class:`WebTlsError` otherwise.
    """
    cert_bytes = cert_pem.strip().encode()
    try:
        certs = x509.load_pem_x509_certificates(cert_bytes)
    except Exception as exc:  # noqa: BLE001
        raise WebTlsError("invalid_certificate") from exc
    if not certs:
        raise WebTlsError("invalid_certificate")
    try:
        key = serialization.load_pem_private_key(key_pem.strip().encode(), password=None)
    except Exception as exc:  # noqa: BLE001
        raise WebTlsError("invalid_private_key") from exc

    leaf = certs[0]
    if _public_bytes(leaf) != _public_bytes(key):
        raise WebTlsError("key_cert_mismatch")

    chain_pem = "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs).strip()
    key_out = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return chain_pem + "\n", key_out


def from_pfx(pfx_der: bytes, password: str | None) -> tuple[str, str]:
    """Parse a PKCS#12/PFX blob into a normalised (cert chain PEM, key PEM)."""
    pw = password.encode() if password else None
    try:
        key, cert, extras = pkcs12.load_key_and_certificates(pfx_der, pw)
    except Exception as exc:  # noqa: BLE001
        raise WebTlsError("invalid_pfx") from exc
    if key is None or cert is None:
        raise WebTlsError("pfx_missing_key_or_cert")

    chain = [cert, *(extras or [])]
    cert_pem = "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in chain)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    # Re-run through normalize_pem to enforce the same match invariant.
    return normalize_pem(cert_pem, key_pem)


def materialize(cert_dir: str, cert_pem: str | None, key_pem: str | None) -> str:
    """Write the effective cert (or a self-signed fallback snippet) into ``cert_dir``.

    Returns ``"custom"`` when a real cert was written, ``"selfsigned"`` otherwise.
    Idempotent; safe to call on every startup and after each settings change.
    """
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, CERT_FILENAME)
    key_path = os.path.join(cert_dir, KEY_FILENAME)
    snippet_path = os.path.join(cert_dir, SNIPPET_FILENAME)

    if cert_pem and key_pem:
        with open(cert_path, "w", encoding="utf-8") as fh:
            fh.write(cert_pem if cert_pem.endswith("\n") else cert_pem + "\n")
        # Private key: create with 0600 before writing any bytes.
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key_pem if key_pem.endswith("\n") else key_pem + "\n")
        with open(snippet_path, "w", encoding="utf-8") as fh:
            fh.write(f"tls {cert_path} {key_path}\n")
        return "custom"

    # No custom cert → self-signed fallback; drop any stale key material.
    for stale in (cert_path, key_path):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass
    with open(snippet_path, "w", encoding="utf-8") as fh:
        fh.write("tls internal\n")
    return "selfsigned"


__all__ = [
    "CERT_FILENAME",
    "KEY_FILENAME",
    "SNIPPET_FILENAME",
    "WebTlsError",
    "from_pfx",
    "materialize",
    "normalize_pem",
]
