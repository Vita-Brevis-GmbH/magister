# /// script
# requires-python = ">=3.10"
# dependencies = ["cryptography>=42"]
# ///
"""Agenten-MSI signieren — für das Selbstupdate (ADR-0014 Nachtrag 2026-10).

Der Normalfall ist die CI: der Schlüssel liegt als GitHub-Secret
``AGENT_SIGNING_KEY``, und agent-ci.yml signiert jedes MSI selbst. Einmal von
Hand nötig ist nur das Erzeugen:

    uv run signieren.py schluessel --fuer-ci

Das druckt den Wert für das Secret und die Zeile für ``update_keys.py``. Der
Schlüssel gehört **nicht** auf die Plattform und auf keinen DC: wer ihn hat,
bringt Code auf die DCs aller Kunden.

Von Hand signieren (ohne CI) geht weiter — eine Datei, ohne den Rest des
Repositorys:

Das MSI selbst braucht es nicht: signiert werden Dateiname, Fassung und
SHA-256. Beides zeigt das Cockpit unter „Agent herunterladen“ (oder
``scripts/agentenpakete.sh zeigen`` auf dem Plattform-Server).

    # einmal: Schlüsselpaar erzeugen (fragt nach einer Passphrase)
    uv run signieren.py schluessel C:\\VB-Signatur\\agent-update.key

    # je Fassung → magister-connector-0.2.410-x64-abc1234.msi.sig
    uv run signieren.py signieren --schluessel C:\\VB-Signatur\\agent-update.key ^
        --datei magister-connector-0.2.410-x64-abc1234.msi --sha256 <64 Hex-Zeichen>

    # oder mit dem MSI daneben (Prüfsumme wird selbst gerechnet)
    uv run signieren.py signieren --schluessel … magister-connector-0.2.410-x64-abc1234.msi

``uv run`` holt ``cryptography`` selbst (Kopf dieser Datei). Ohne uv:
``py -m pip install cryptography`` und ``py signieren.py …``.

Die ``.sig`` gehört neben das MSI ins Paketverzeichnis der Konsole
(``scripts/agentenpakete.sh signatur <datei.sig>`` auf dem Plattform-Server).
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

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_FASSUNG = re.compile(r"^magister-connector-(\d+\.\d+\.\d+)-x64(?:-[0-9a-f]{6,40})?\.msi$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def signed_message(filename: str, version: str, sha256: str) -> bytes:
    """Muss Byte für Byte ``connector_agent.update.signed_message`` sein (Test prüft es)."""
    return f"magister-connector-update/v1\n{filename}\n{version}\n{sha256.lower()}\n".encode()


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_bytes(pem)
    raw = _public_raw(private)
    return key_id(raw), base64.b64encode(raw).decode()


def create_ci_key() -> tuple[str, str, str]:
    """Schlüsselpaar für die CI: (Secret-Wert, Schlüssel-ID, öffentlicher Schlüssel).

    Der Secret-Wert sind die 32 Byte des privaten Schlüssels, Base64. Ohne
    Passphrase — GitHub verwahrt ihn verschlüsselt und gibt ihn nur an Läufe
    des Repositorys heraus.
    """
    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    raw = _public_raw(private)
    return base64.b64encode(seed).decode(), key_id(raw), base64.b64encode(raw).decode()


def load_key_from_env(name: str) -> Ed25519PrivateKey:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} ist leer.")
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(value))
    except ValueError as exc:
        raise SystemExit(f"{name} ist kein Ed25519-Schlüssel (32 Byte, Base64).") from exc


def pinned_keys(update_keys_py: Path) -> dict[str, str]:
    """``TRUSTED_KEYS`` aus ``update_keys.py`` lesen, ohne die Datei auszuführen."""
    import ast

    tree = ast.parse(update_keys_py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "TRUSTED_KEYS":
            value = getattr(node, "value", None)
            if value is not None:
                return {str(k): str(v) for k, v in ast.literal_eval(value).items()}
    return {}


def load_key(path: Path, passphrase: bytes) -> Ed25519PrivateKey:
    private = serialization.load_pem_private_key(path.read_bytes(), password=passphrase)
    if not isinstance(private, Ed25519PrivateKey):
        raise SystemExit(f"{path} ist kein Ed25519-Schlüssel.")
    return private


def signature_for(filename: str, sha256: str, private: Ed25519PrivateKey) -> dict[str, str]:
    """Inhalt der ``.sig``: Schlüssel-ID und Signatur, dazu was signiert ist."""
    match = _FASSUNG.match(filename)
    if match is None:
        raise SystemExit(f"{filename}: keine Fassung im Namen (magister-connector-x.y.z-x64….msi).")
    sha = sha256.strip().lower()
    if not _SHA.match(sha):
        raise SystemExit("Die SHA-256 muss aus 64 Hex-Zeichen bestehen.")
    version = match.group(1)
    signature = private.sign(signed_message(filename, version, sha))
    return {
        "key_id": key_id(_public_raw(private)),
        "signature": base64.b64encode(signature).decode(),
        "filename": filename,
        "version": version,
        "sha256": sha,
    }


def write_sig(target_dir: Path, data: dict[str, str]) -> Path:
    sig = target_dir / f"{data['filename']}.sig"
    sig.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return sig


def sign_msi(msi: Path, private: Ed25519PrivateKey) -> Path:
    """``<msi>.sig`` neben dem MSI — Prüfsumme aus der Datei."""
    sha = hashlib.sha256(msi.read_bytes()).hexdigest()
    return write_sig(msi.parent, signature_for(msi.name, sha, private))


def verify(data: dict[str, str], public_b64: str) -> bool:
    """Gegenprobe mit einem öffentlichen Schlüssel, wie der Agent sie macht."""
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64)).verify(
            base64.b64decode(data["signature"]),
            signed_message(data["filename"], data["version"], data["sha256"]),
        )
    except (InvalidSignature, ValueError, KeyError):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agenten-MSI für das Selbstupdate signieren.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    neu = sub.add_parser("schluessel", help="Schlüsselpaar erzeugen")
    neu.add_argument("datei", type=Path, nargs="?", help="Schlüsseldatei (für Signieren von Hand)")
    neu.add_argument(
        "--fuer-ci", action="store_true", help="Wert für das GitHub-Secret AGENT_SIGNING_KEY"
    )
    sig = sub.add_parser("signieren", help="MSI signieren → <msi>.sig")
    sig.add_argument("--schluessel", type=Path, help="Schlüsseldatei mit Passphrase")
    sig.add_argument("--schluessel-env", help="Umgebungsvariable mit dem Schlüssel (CI)")
    sig.add_argument(
        "--pruefe-gegen",
        type=Path,
        help="update_keys.py: Abbruch, wenn der Schlüssel dort nicht eingebaut ist",
    )
    sig.add_argument("--datei", help="Dateiname des MSI (ohne das MSI selbst)")
    sig.add_argument("--sha256", help="SHA-256 des MSI, wie das Cockpit sie zeigt")
    sig.add_argument("msi", type=Path, nargs="*", help="oder: MSI-Dateien hier")
    chk = sub.add_parser("pruefen", help="eine .sig gegen einen öffentlichen Schlüssel prüfen")
    chk.add_argument("--oeffentlich", required=True, help="öffentlicher Schlüssel (Base64)")
    chk.add_argument("sig", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.cmd == "schluessel" and args.fuer_ci:
        secret, kid, public = create_ci_key()
        sys.stdout.write(
            "1) GitHub → Repository → Settings → Secrets and variables → Actions →\n"
            "   New repository secret, Name AGENT_SIGNING_KEY, Wert:\n\n"
            f"   {secret}\n\n"
            "   (Nirgends sonst ablegen; danach dieses Fenster schliessen.)\n\n"
            "2) In agent/connector_agent/update_keys.py eintragen:\n\n"
            f'   TRUSTED_KEYS: dict[str, str] = {{"{kid}": "{public}"}}\n'
        )
        return 0
    if args.cmd == "schluessel":
        if args.datei is None:
            parser.error("Schlüsseldatei angeben — oder --fuer-ci")
        kid, public = create_key(args.datei, _passphrase(confirm=True))
        sys.stdout.write(
            f"Privater Schlüssel: {args.datei}  (offline aufbewahren, mit Sicherung)\n"
            f"Schlüssel-ID:       {kid}\n"
            f"Öffentlich:         {public}\n\n"
            "Für agent/connector_agent/update_keys.py:\n"
            f'    TRUSTED_KEYS: dict[str, str] = {{"{kid}": "{public}"}}\n'
        )
        return 0
    if args.cmd == "signieren":
        if not args.msi and not (args.datei and args.sha256):
            parser.error("entweder MSI-Dateien oder --datei mit --sha256")
        if args.schluessel_env:
            private = load_key_from_env(args.schluessel_env)
        elif args.schluessel:
            private = load_key(args.schluessel, _passphrase(confirm=False))
        else:
            parser.error("--schluessel oder --schluessel-env")
        if args.pruefe_gegen:
            kid = key_id(_public_raw(private))
            pinned = pinned_keys(args.pruefe_gegen)
            if not pinned:
                sys.stderr.write(
                    "Hinweis: im Agenten ist noch kein Schlüssel eingebaut — die Signatur "
                    "entsteht, prüfen kann sie erst ein Agent mit Schlüssel.\n"
                )
            elif kid not in pinned:
                raise SystemExit(
                    f"Der Schlüssel {kid} steht nicht in {args.pruefe_gegen} — die Agenten "
                    "würden diese Signatur ablehnen."
                )
        if args.datei:
            out = write_sig(Path.cwd(), signature_for(args.datei, args.sha256 or "", private))
            sys.stdout.write(f"{out}\n")
        for msi in args.msi:
            sys.stdout.write(f"{sign_msi(msi, private)}\n")
        return 0
    failed = 0
    for path in args.sig:
        data = json.loads(path.read_text(encoding="utf-8"))
        ok = verify(data, args.oeffentlich)
        sys.stdout.write(f"{path.name}: {'gültig' if ok else 'UNGÜLTIG'}\n")
        failed |= not ok
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
