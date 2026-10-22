"""Signierwerkzeug: was es signiert, prüft der Agent mit demselben Schlüssel als gültig."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from connector_agent import update as up

NAME = "magister-connector-0.2.250-x64-abc1234.msi"


def _tool() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "packaging" / "signieren.py"
    spec = importlib.util.spec_from_file_location("signieren", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_signed_by_the_tool_valid_in_the_agent(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    kid, public = tool.create_key(key, b"eine lange passphrase")
    if sys.platform != "win32":  # Windows kennt keine Unix-Rechte
        assert oct(key.stat().st_mode & 0o777) == "0o600"
    msi = tmp_path / NAME
    msi.write_bytes(b"MSI")
    sig = tool.sign_msi(msi, tool.load_key(key, b"eine lange passphrase"))
    data = json.loads(sig.read_text())
    assert data["key_id"] == kid and data["version"] == "0.2.250"
    assert tool.verify_msi(msi, {kid: public}) == kid

    # Geänderte Datei: Signatur passt nicht mehr.
    msi.write_bytes(b"MSI mit Zusatz")
    with pytest.raises(up.UpdateError, match="stimmt nicht"):
        tool.verify_msi(msi, {kid: public})


def test_a_key_is_never_overwritten_and_needs_the_passphrase(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    tool.create_key(key, b"eine lange passphrase")
    with pytest.raises(SystemExit, match="gibt es schon"):
        tool.create_key(key, b"eine lange passphrase")
    with pytest.raises(ValueError):
        tool.load_key(key, b"falsch")


def test_only_versioned_packages_are_signed(tmp_path: Path) -> None:
    tool = _tool()
    key = tmp_path / "update.key"
    tool.create_key(key, b"eine lange passphrase")
    msi = tmp_path / "irgendwas.msi"
    msi.write_bytes(b"MSI")
    with pytest.raises(SystemExit, match="keine Fassung"):
        tool.sign_msi(msi, tool.load_key(key, b"eine lange passphrase"))
