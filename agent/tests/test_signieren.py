"""Signierwerkzeug: was es signiert, prüft der Agent mit demselben Schlüssel als gültig."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from connector_agent import update as up

NAME = "magister-connector-0.2.250-x64-abc1234.msi"
PASS = b"eine lange passphrase"


def _tool() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "packaging" / "signieren.py"
    spec = importlib.util.spec_from_file_location("signieren", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _info(data: dict[str, str]) -> up.UpdateInfo:
    return up.UpdateInfo(
        filename=data["filename"],
        version=data["version"],
        sha256=data["sha256"],
        size_bytes=1,
        key_id=data["key_id"],
        signature=data["signature"],
    )


def test_the_tool_signs_the_same_message_the_agent_checks() -> None:
    """Das Werkzeug steht allein (ohne Repository) — die Nachricht muss trotzdem dieselbe sein."""
    tool = _tool()
    assert tool.signed_message(NAME, "0.2.250", "A" * 64) == up.signed_message(
        NAME, "0.2.250", "A" * 64
    )


def test_signed_by_name_and_checksum_valid_in_the_agent(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    kid, public = tool.create_key(key, PASS)
    if sys.platform != "win32":  # Windows kennt keine Unix-Rechte
        assert oct(key.stat().st_mode & 0o777) == "0o600"
    sha = hashlib.sha256(b"MSI").hexdigest()
    data = tool.signature_for(NAME, sha.upper(), tool.load_key(key, PASS))
    assert data["key_id"] == kid and data["version"] == "0.2.250" and data["sha256"] == sha
    up.verify_signature(_info(data), {kid: public})
    assert tool.verify(data, public)

    # Andere Prüfsumme: Signatur passt nicht mehr.
    with pytest.raises(up.UpdateError, match="stimmt nicht"):
        up.verify_signature(_info({**data, "sha256": "0" * 64}), {kid: public})


def test_with_the_msi_at_hand_the_checksum_is_computed(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    kid, public = tool.create_key(key, PASS)
    msi = tmp_path / NAME
    msi.write_bytes(b"MSI")
    sig = tool.sign_msi(msi, tool.load_key(key, PASS))
    data = json.loads(sig.read_text())
    assert data["sha256"] == hashlib.sha256(b"MSI").hexdigest()
    up.verify_signature(_info(data), {kid: public})


def test_a_key_is_never_overwritten_and_needs_the_passphrase(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    tool.create_key(key, PASS)
    with pytest.raises(SystemExit, match="gibt es schon"):
        tool.create_key(key, PASS)
    with pytest.raises(ValueError):
        tool.load_key(key, b"falsch")


def test_only_versioned_names_and_real_checksums(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    tool.create_key(key, PASS)
    private = tool.load_key(key, PASS)
    with pytest.raises(SystemExit, match="keine Fassung"):
        tool.signature_for("irgendwas.msi", "a" * 64, private)
    with pytest.raises(SystemExit, match="64 Hex"):
        tool.signature_for(NAME, "abc", private)
