"""Agenten-MSI signieren — für das Selbstupdate (ADR-0014 Nachtrag 2026-10).

Läuft **offline**, auf dem Rechner, auf dem der private Schlüssel liegt —
nicht auf der Plattform und nicht in der CI. Wer den Schlüssel hat, kann Code
auf den Domänencontrollern aller Kunden bringen.

    # einmal: Schlüsselpaar erzeugen (fragt nach einer Passphrase)
    uv run python packaging/signieren.py schluessel ~/vb-agent-update.key

    # je Fassung: MSI signieren → <msi>.sig daneben
    uv run python packaging/signieren.py signieren --schluessel ~/vb-agent-update.key \\
        magister-connector-0.2.250-x64-abc1234.msi

    # Gegenprobe mit den im Agenten eingebauten Schlüsseln
    uv run python packaging/signieren.py pruefen magister-connector-0.2.250-x64-abc1234.msi

MSI und ``.sig`` gehören zusammen ins Paketverzeichnis der Konsole
(``COCKPIT_AGENT_PACKAGE_DIR``).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from connector_agent import update as up
from connector_agent.update_keys import TRUSTED_KEYS

_FASSUNG = re.compile(r"^magister-connector-(\d+\.\d+\.\d+)-x64(?:-[0-9a-f]{6,40})?\.msi$")


def key_id(public_raw: bytes) -> str:
    """Kurz und eindeutig genug: die ersten 16 Hex-Zeichen der SHA-256."""
    return hashlib.sha256(public_raw).hexdigest()[:16]


def _public_raw(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _passphrase(confirm: bool) -> bytes:
    env = os.environ.get("MAGISTER_SIGNIER_PASSPHRASE")
    if env:
        return env.encode()
    first = getpass.getpass("Passphrase des Signaturschlüssels: ")
    if confirm and getpass.getpass("Noch einmal: ") != first:
        raise SystemExit("Die beiden Eingaben stimmen nicht überein.")
    if len(first) < 12:
        raise SystemExit("Mindestens 12 Zeichen.")
    return first.encode()


def create_key(path: Path, passphrase: bytes) -> tuple[str, str]:
    """Schlüsselpaar anlegen. Rückgabe: (Schlüssel-ID, öffentlicher Schlüssel Base64)."""
    if path.exists():
        raise SystemExit(f"{path} gibt es schon — ein Schlüssel wird nie überschrieben.")
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase),
    )
    path.touch(mode=0o600)
    path.write_bytes(pem)
    raw = _public_raw(private)
    return key_id(raw), base64.b64encode(raw).decode()


def load_key(path: Path, passphrase: bytes) -> Ed25519PrivateKey:
    private = serialization.load_pem_private_key(path.read_bytes(), password=passphrase)
    if not isinstance(private, Ed25519PrivateKey):
        raise SystemExit(f"{path} ist kein Ed25519-Schlüssel.")
    return private


def sign_msi(msi: Path, private: Ed25519PrivateKey) -> Path:
    """``<msi>.sig`` schreiben: Schlüssel-ID und Signatur über Name, Fassung, SHA-256."""
    match = _FASSUNG.match(msi.name)
    if match is None:
        raise SystemExit(f"{msi.name}: keine Fassung im Namen (magister-connector-x.y.z-x64….msi).")
    sha = hashlib.sha256(msi.read_bytes()).hexdigest()
    version = match.group(1)
    signature = private.sign(up.signed_message(msi.name, version, sha))
    sig = msi.with_name(msi.name + ".sig")
    sig.write_text(
        json.dumps(
            {
                "key_id": key_id(_public_raw(private)),
                "signature": base64.b64encode(signature).decode(),
                "filename": msi.name,
                "version": version,
                "sha256": sha,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return sig


def verify_msi(msi: Path, keys: dict[str, str]) -> str:
    """Gegenprobe wie im Agenten. Rückgabe: die Schlüssel-ID."""
    data = json.loads(msi.with_name(msi.name + ".sig").read_text(encoding="utf-8"))
    match = _FASSUNG.match(msi.name)
    info = up.UpdateInfo(
        filename=msi.name,
        version=match.group(1) if match else "",
        sha256=hashlib.sha256(msi.read_bytes()).hexdigest(),
        size_bytes=msi.stat().st_size,
        key_id=str(data.get("key_id") or ""),
        signature=str(data.get("signature") or ""),
    )
    up.verify_signature(info, keys)
    return info.key_id or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    neu = sub.add_parser("schluessel", help="Schlüsselpaar erzeugen")
    neu.add_argument("datei", type=Path)
    sig = sub.add_parser("signieren", help="MSI signieren")
    sig.add_argument("--schluessel", type=Path, required=True)
    sig.add_argument("msi", type=Path, nargs="+")
    chk = sub.add_parser("pruefen", help="Signatur gegen die eingebauten Schlüssel prüfen")
    chk.add_argument("msi", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.cmd == "schluessel":
        kid, public = create_key(args.datei, _passphrase(confirm=True))
        sys.stdout.write(
            f"Privater Schlüssel: {args.datei} (offline aufbewahren, mit Sicherung)\n"
            f"Schlüssel-ID:       {kid}\n"
            f"Öffentlich:         {public}\n\n"
            "In agent/connector_agent/update_keys.py eintragen:\n"
            f'    TRUSTED_KEYS: dict[str, str] = {{"{kid}": "{public}"}}\n'
        )
        return 0
    if args.cmd == "signieren":
        private = load_key(args.schluessel, _passphrase(confirm=False))
        for msi in args.msi:
            sys.stdout.write(f"{sign_msi(msi, private)}\n")
        return 0
    if not TRUSTED_KEYS:
        sys.stderr.write("Im Agenten ist noch kein Schlüssel eingebaut (update_keys.py).\n")
        return 1
    failed = 0
    for msi in args.msi:
        try:
            sys.stdout.write(f"{msi.name}: gültig (Schlüssel {verify_msi(msi, TRUSTED_KEYS)})\n")
        except (up.UpdateError, OSError, ValueError) as exc:
            sys.stderr.write(f"{msi.name}: {exc}\n")
            failed = 1
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
