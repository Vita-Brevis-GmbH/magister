"""Selbstupdate im Wartungsfenster: nur signiert, nur im Fenster, ein Versuch je Paket."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from connector_agent import remote as remote_cfg
from connector_agent import update as up
from connector_agent.autoupdate import CHECK_SECONDS, AutoUpdater
from connector_agent.config import AgentConfig, AgentSecrets
from tests.helpers import FakeCa, write_enrolled_state

MSI = b"neues MSI " * 500
NAME = "magister-connector-0.2.250-x64-abc1234.msi"
SHA = hashlib.sha256(MSI).hexdigest()
SECRETS = AgentSecrets(agent_id="a", api_key="k", result_hmac_key="h", spki_sha256="f")
NIGHT = dt.datetime(2026, 10, 23, 2, 30)
NOON = dt.datetime(2026, 10, 23, 12, 0)


def _keys() -> tuple[Ed25519PrivateKey, dict[str, str]]:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, {"k1": base64.b64encode(raw).decode()}


class Platform:
    """Bietet ein MSI an und schreibt mit, was gemeldet wird."""

    def __init__(self, signer: Ed25519PrivateKey | None, version: str = "0.2.250") -> None:
        self.reports: list[str] = []
        self.downloads = 0
        self.offer: dict[str, Any] = {
            "filename": NAME,
            "version": version,
            "sha256": SHA,
            "size_bytes": len(MSI),
        }
        if signer is not None:
            sig = signer.sign(up.signed_message(NAME, version, SHA))
            self.offer |= {"key_id": "k1", "signature": base64.b64encode(sig).decode()}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/connector/update":
            return httpx.Response(200, json=self.offer)
        if request.url.path == "/connector/update/package":
            self.downloads += 1
            return httpx.Response(200, content=MSI)
        if request.url.path == "/connector/update/result":
            self.reports.append(json.loads(request.content)["outcome"])
            return httpx.Response(204)
        return httpx.Response(404)


def _config(tmp_path: Path) -> AgentConfig:
    write_enrolled_state(tmp_path, FakeCa())
    return AgentConfig.from_mapping(
        {
            "endpoint": "https://connect.magister.test:46200",
            "state_dir": str(tmp_path),
            "ca_bundle": str(tmp_path / "ca.pem"),
        }
    )


def _updater(
    tmp_path: Path,
    platform: Platform,
    keys: dict[str, str],
    *,
    at: dt.datetime = NIGHT,
    running: str = "0.2.190",
) -> tuple[AutoUpdater, list[tuple[Path, Path | None]]]:
    launched: list[tuple[Path, Path | None]] = []

    def launcher(msi: Path, previous: Path | None) -> Path:
        launched.append((msi, previous))
        return msi.with_suffix(".log")

    updater = AutoUpdater(
        config=_config(tmp_path),
        secrets=SECRETS,
        agent_version=running,
        keys=keys,
        launcher=launcher,
        clock=lambda: at,
        transport=httpx.MockTransport(platform),
    )
    return updater, launched


REMOTE = remote_cfg.RemoteConfig(allowed_ous=frozenset(), protected_groups=frozenset())


class TestWindow:
    @pytest.mark.parametrize(
        ("window", "moment", "inside"),
        [
            ("02:00-04:00", dt.time(2, 0), True),
            ("02:00-04:00", dt.time(3, 59), True),
            ("02:00-04:00", dt.time(4, 0), False),
            ("22:00-02:00", dt.time(23, 30), True),
            ("22:00-02:00", dt.time(1, 0), True),
            ("22:00-02:00", dt.time(12, 0), False),
            ("kaputt", dt.time(2, 30), True),  # Vorgabe 02:00-04:00
        ],
    )
    def test_in_window(self, window: str, moment: dt.time, inside: bool) -> None:
        assert remote_cfg.in_window(window, moment) is inside

    def test_the_platform_sets_switch_and_window(self) -> None:
        parsed = remote_cfg.parse({"auto_update": False, "update_window": "01:00-03:00"})
        assert (parsed.auto_update, parsed.update_window) == (False, "01:00-03:00")
        # Fehlt beides (ältere Plattform): an, Vorgabefenster.
        parsed = remote_cfg.parse({"update_window": "25:00-03:00"})
        assert (parsed.auto_update, parsed.update_window) == (True, "02:00-04:00")


class TestAutoUpdate:
    def test_a_signed_newer_package_is_installed_in_the_window(self, tmp_path: Path) -> None:
        private, keys = _keys()
        platform = Platform(private)
        updater, launched = _updater(tmp_path, platform, keys)
        previous = up.updates_dir(updater.config) / "magister-connector-0.2.190-x64.msi"
        previous.parent.mkdir(parents=True)
        previous.write_bytes(b"alt")

        assert updater.tick(REMOTE) == "0.2.250"
        assert launched == [(up.updates_dir(updater.config) / NAME, previous)]
        assert "Signatur gültig, Installation gestartet" in platform.reports[0]
        # Dasselbe Paket nicht noch einmal — auch nicht in der nächsten Runde.
        assert updater.tick(REMOTE) is None
        assert len(launched) == 1

    def test_outside_the_window_or_switched_off_nothing_happens(self, tmp_path: Path) -> None:
        private, keys = _keys()
        platform = Platform(private)
        updater, launched = _updater(tmp_path, platform, keys, at=NOON)
        assert updater.tick(REMOTE) is None
        updater.clock = lambda: NIGHT
        off = remote_cfg.RemoteConfig(
            allowed_ous=frozenset(), protected_groups=frozenset(), auto_update=False
        )
        assert updater.tick(off) is None
        assert launched == []
        assert platform.downloads == 0

    def test_an_unsigned_package_is_reported_once_and_never_installed(self, tmp_path: Path) -> None:
        _private, keys = _keys()
        platform = Platform(None)
        updater, launched = _updater(tmp_path, platform, keys)
        assert updater.tick(REMOTE) is None
        assert updater.tick(REMOTE) is None
        assert launched == []
        assert platform.downloads == 0
        assert len(platform.reports) == 1
        assert "nicht signiert" in platform.reports[0]

    def test_a_package_signed_by_someone_else_is_refused(self, tmp_path: Path) -> None:
        _private, keys = _keys()
        intruder, _ = _keys()
        platform = Platform(intruder)
        updater, launched = _updater(tmp_path, platform, keys)
        assert updater.tick(REMOTE) is None
        assert launched == []
        assert "stimmt nicht" in platform.reports[0]

    def test_without_a_built_in_key_there_is_no_self_update(self, tmp_path: Path) -> None:
        private, _ = _keys()
        platform = Platform(private)
        updater, launched = _updater(tmp_path, platform, {})
        assert updater.tick(REMOTE) is None
        assert launched == []

    def test_an_up_to_date_agent_stays(self, tmp_path: Path) -> None:
        private, keys = _keys()
        platform = Platform(private)
        updater, launched = _updater(tmp_path, platform, keys, running="0.2.250 (abc1234)")
        assert updater.tick(REMOTE) is None
        assert launched == []

    def test_the_install_result_is_reported_once_by_the_new_agent(self, tmp_path: Path) -> None:
        private, keys = _keys()
        platform = Platform(private)
        updater, _ = _updater(tmp_path, platform, keys, at=NOON, running="0.2.250")
        folder = up.updates_dir(updater.config)
        folder.mkdir(parents=True)
        (folder / up.RESULT_FILE).write_text(f"{NAME} msiexec:0 gesund\n")
        updater.tick(REMOTE)
        updater.tick(REMOTE)
        assert len(platform.reports) == 1
        assert "läuft jetzt 0.2.250" in platform.reports[0]
        assert "msiexec:0 gesund" in platform.reports[0]

    def test_rounds_are_spaced(self, tmp_path: Path) -> None:
        private, keys = _keys()
        updater, _ = _updater(tmp_path, Platform(private), keys)
        assert updater.due(100.0)
        assert not updater.due(100.0 + CHECK_SECONDS - 1)
        assert updater.due(100.0 + CHECK_SECONDS)
