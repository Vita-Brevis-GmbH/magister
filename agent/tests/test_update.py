"""``magister-connector update``: prüfen, laden, Prüfsumme, einspielen.

Von Hand ruft ein Mensch auf dem DC den Befehl auf; das Selbstupdate im
Wartungsfenster prüft ``tests/test_autoupdate.py``. Geprüft wird hier, dass
er nur Neueres nimmt, nur eine Datei mit stimmender Prüfsumme behält, die
Signatur prüft und das Einspielen so anstösst, dass der Dienst danach wieder
läuft — oder auf die alte Fassung zurückfällt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from connector_agent import cli
from connector_agent import update as up
from connector_agent.config import AgentConfig, AgentSecrets
from tests.helpers import FakeCa, write_enrolled_state

MSI = b"MSI-Inhalt " * 1000
NAME = "magister-connector-0.2.250-x64-abc1234.msi"
SECRETS = AgentSecrets(agent_id="a", api_key="k", result_hmac_key="h", spki_sha256="f")


def _config(tmp_path: Path) -> AgentConfig:
    write_enrolled_state(tmp_path, FakeCa())
    return AgentConfig.from_mapping(
        {
            "endpoint": "https://connect.magister.test:46200",
            "state_dir": str(tmp_path),
            "ca_bundle": str(tmp_path / "ca.pem"),
        }
    )


def _platform(*, body: bytes = MSI, sha: str | None = None, status: int = 200) -> Any:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["X-Connector-Api-Key"] == "k"
        if request.url.path == "/connector/update":
            if status != 200:
                return httpx.Response(status, json={"detail": "nein"})
            return httpx.Response(
                200,
                json={
                    "filename": NAME,
                    "version": "0.2.250",
                    "sha256": sha or hashlib.sha256(MSI).hexdigest(),
                    "size_bytes": len(MSI),
                },
            )
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


class TestVersions:
    @pytest.mark.parametrize(
        ("available", "running", "newer"),
        [
            ("0.2.250", "0.2.190", True),
            ("0.2.250", "0.2.250 (abc1234)", False),
            ("0.2.190", "0.2.250", False),
            ("0.3.1", "0.2.999", True),
            ("0.2.250", "0.2.0", True),
            ("kaputt", "0.2.0", False),
        ],
    )
    def test_only_newer_counts(self, available: str, running: str, newer: bool) -> None:
        assert up.is_newer(available, running) is newer


class TestCheckAndDownload:
    def test_check_reads_what_is_offered(self, tmp_path: Path) -> None:
        info = up.check(_config(tmp_path), SECRETS, agent_version="0.2.190", transport=_platform())
        assert info is not None
        assert (info.version, info.filename) == ("0.2.250", NAME)

    def test_nothing_offered_is_not_an_error(self, tmp_path: Path) -> None:
        info = up.check(
            _config(tmp_path), SECRETS, agent_version="0.2.190", transport=_platform(status=404)
        )
        assert info is None

    def test_a_good_download_lands_in_the_state_dir(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        alt = tmp_path / "updates" / "magister-connector-0.2.100-x64-0000000.msi"
        alt.parent.mkdir()
        alt.write_bytes(b"alt")
        transport = _platform()
        info = up.check(config, SECRETS, agent_version="0.2.190", transport=transport)
        assert info is not None
        msi = up.download(config, SECRETS, info, agent_version="0.2.190", transport=transport)
        assert msi == tmp_path / "updates" / NAME
        assert msi.read_bytes() == MSI
        assert not alt.exists(), "frühere Updates werden weggeräumt"

    def test_a_wrong_checksum_keeps_nothing(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        transport = _platform(body=b"manipuliert")
        info = up.check(config, SECRETS, agent_version="0.2.190", transport=transport)
        assert info is not None
        with pytest.raises(up.UpdateError, match="Prüfsumme"):
            up.download(config, SECRETS, info, agent_version="0.2.190", transport=transport)
        assert list((tmp_path / "updates").iterdir()) == []

    def test_a_strange_filename_is_refused(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"filename": "..\\\\böse.exe", "version": "9.9.9", "sha256": "0" * 64},
            )

        with pytest.raises(up.UpdateError, match="gültiges"):
            up.check(
                _config(tmp_path),
                SECRETS,
                agent_version="0.2.190",
                transport=httpx.MockTransport(handler),
            )


class TestInstallScript:
    def test_it_installs_quietly_and_starts_the_service(self) -> None:
        script = up.install_script(Path(r"C:\Daten\x.msi"), Path(r"C:\Daten\x.log"))
        assert (
            'msiexec /i "C:\\Daten\\x.msi" /qn /norestart REINSTALLMODE=amus '
            '/l*v "C:\\Daten\\x.log"' in script
        )
        assert script.index("msiexec") < script.index("sc start MagisterConnector")
        assert "\r\n" in script

    def test_it_waits_for_the_service_before_installing(self) -> None:
        """`sc stop` kehrt sofort zurück; laufende Dateien überlebt das MSI nicht sauber."""
        script = up.install_script(Path(r"C:\Daten\x.msi"), Path(r"C:\Daten\x.log"))
        assert script.index('findstr /c:"STOPPED"') < script.index("msiexec /i")
        assert script.index("taskkill /f /im magister-connector-service.exe") < script.index(
            "msiexec /i"
        )

    def test_a_missing_python_dll_is_repaired_and_reported(self) -> None:
        script = up.install_script(
            Path(r"C:\Daten\x.msi"),
            Path(r"C:\Daten\x.log"),
            target=Path(r"C:\Program Files\Magister Connector"),
        )
        dll = r"C:\Program Files\Magister Connector\_internal\python3*.dll"
        assert f'if exist "{dll}" goto fertig' in script
        assert script.index("msiexec /i") < script.index('msiexec /fa "C:\\Daten\\x.msi"')
        assert 'update-ergebnis.txt"' in script

    def test_outside_windows_nothing_is_started(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(up, "IS_WINDOWS", False)
        with pytest.raises(up.UpdateError, match="Windows"):
            up.launch_install(tmp_path / NAME)


class TestCommand:
    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        *args: str,
        offered: str = "0.2.250",
        check: bool = True,
    ) -> tuple[int, str, list[Path]]:
        config = _config(tmp_path)
        (tmp_path / "secrets.json").write_text(
            '{"agent_id":"a","api_key":"k","result_hmac_key":"h","spki_sha256":"f"}'
        )
        (tmp_path / "secrets.json").chmod(0o600)
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "endpoint": config.endpoint,
                    "state_dir": str(tmp_path),
                    "ca_bundle": str(tmp_path / "ca.pem"),
                }
            )
        )
        launched: list[Path] = []

        def _check(*_a: Any, **_k: Any) -> up.UpdateInfo:
            return up.UpdateInfo(NAME, offered, "0" * 64, 1)

        def _download(*_a: Any, **_k: Any) -> Path:
            return tmp_path / "updates" / NAME

        def _launch(msi: Path, previous: Path | None = None) -> Path:
            launched.append(msi)
            return msi.with_suffix(".log")

        if check:
            monkeypatch.setattr(up, "check", _check)
        monkeypatch.setattr(up, "download", _download)
        monkeypatch.setattr(up, "launch_install", _launch)
        monkeypatch.setattr("connector_agent.uninstall.is_admin", lambda: True)
        monkeypatch.setattr(cli, "VERSION", "0.2.190")
        code = cli.main(["--config", str(path), "update", *args])
        out = capsys.readouterr()
        return code, out.out + out.err, launched

    def test_an_update_is_launched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, text, launched = self._run(tmp_path, monkeypatch, capsys, "--ja")
        assert code == 0
        assert launched == [tmp_path / "updates" / NAME]
        assert "Dienst startet danach" in text

    def test_only_checking_changes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, text, launched = self._run(tmp_path, monkeypatch, capsys, "--nur-pruefen")
        assert code == 0
        assert launched == []
        assert "Update verfügbar" in text

    def test_an_up_to_date_agent_does_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, text, launched = self._run(tmp_path, monkeypatch, capsys, "--ja", offered="0.2.190")
        assert code == 0
        assert launched == []
        assert "aktuell" in text


def _keypair() -> tuple[Any, dict[str, str]]:
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, {"k1": base64.b64encode(raw).decode()}


def _signed(private: Any, info: up.UpdateInfo, key_id: str = "k1") -> up.UpdateInfo:
    import base64
    import dataclasses

    sig = private.sign(up.signed_message(info.filename, info.version, info.sha256))
    return dataclasses.replace(info, key_id=key_id, signature=base64.b64encode(sig).decode())


class TestSignature:
    INFO = up.UpdateInfo(NAME, "0.2.250", "a" * 64, 1)

    def test_a_valid_signature_passes(self) -> None:
        private, keys = _keypair()
        up.verify_signature(_signed(private, self.INFO), keys)

    def test_missing_unknown_or_foreign_signatures_are_refused(self) -> None:

        private, keys = _keypair()
        with pytest.raises(up.UpdateError, match="nicht signiert"):
            up.verify_signature(self.INFO, keys)
        with pytest.raises(up.UpdateError, match="unbekannten Schlüssel"):
            up.verify_signature(_signed(private, self.INFO, key_id="k9"), keys)
        other, _ = _keypair()
        with pytest.raises(up.UpdateError, match="stimmt nicht"):
            up.verify_signature(_signed(other, self.INFO), keys)

    def test_the_signature_binds_checksum_and_version(self) -> None:
        """Eine Signatur gilt nur für ihre Datei — und nicht als neuere Fassung."""
        import dataclasses

        private, keys = _keypair()
        good = _signed(private, self.INFO)
        with pytest.raises(up.UpdateError, match="stimmt nicht"):
            up.verify_signature(dataclasses.replace(good, sha256="b" * 64), keys)
        with pytest.raises(up.UpdateError, match="stimmt nicht"):
            up.verify_signature(dataclasses.replace(good, version="0.2.999"), keys)

    def test_check_reads_the_signature_from_the_platform(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "filename": NAME,
                    "version": "0.2.250",
                    "sha256": "a" * 64,
                    "size_bytes": 1,
                    "key_id": "k1",
                    "signature": "c2ln",
                },
            )

        info = up.check(
            _config(tmp_path),
            SECRETS,
            agent_version="0.2.190",
            transport=httpx.MockTransport(handler),
        )
        assert info is not None
        assert (info.key_id, info.signature) == ("k1", "c2ln")


class TestRollback:
    def test_with_the_previous_package_a_sick_install_is_rolled_back(self) -> None:
        script = up.install_script(
            Path(r"C:\Daten\neu.msi"), Path(r"C:\Daten\neu.log"), previous=Path(r"C:\Daten\alt.msi")
        )
        assert script.index('findstr /c:"RUNNING"') < script.index(
            'msiexec /x "C:\\Daten\\neu.msi"'
        )
        assert script.index('msiexec /x "C:\\Daten\\neu.msi"') < script.index(
            'msiexec /i "C:\\Daten\\alt.msi"'
        )
        assert "rueckfall" in script
        # Jede Sprungmarke genau einmal — cmd springt sonst an die erste.
        labels = [line for line in script.split("\r\n") if line.startswith(":")]
        assert len(labels) == len(set(labels))

    def test_without_it_the_result_says_so_but_nothing_is_removed(self) -> None:
        script = up.install_script(Path(r"C:\Daten\neu.msi"), Path(r"C:\Daten\neu.log"))
        assert "msiexec /x" not in script
        assert "gesund:nein" in script

    def test_the_running_versions_package_survives_a_download(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        folder = up.updates_dir(config)
        folder.mkdir()
        alt = folder / "magister-connector-0.2.190-x64-def5678.msi"
        alt.write_bytes(b"alt")
        fremd = folder / "magister-connector-0.2.100-x64.msi"
        fremd.write_bytes(b"uralt")
        merkzettel = folder / "versuch-0.2.200-aaaaaaaaaaaa.txt"
        merkzettel.write_text("x")
        sha = hashlib.sha256(MSI).hexdigest()
        up.download(
            config,
            SECRETS,
            up.UpdateInfo(NAME, "0.2.250", sha, len(MSI)),
            agent_version="0.2.190 (def5678)",
            transport=_platform(),
        )
        assert alt.exists() and merkzettel.exists()
        assert not fremd.exists()
        assert up.msi_for_version(config, "0.2.190 (def5678)") == alt
        assert up.msi_for_version(config, "0.2.191") is None


class TestCommandSignature:
    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        *args: str,
        signed: bool,
    ) -> tuple[int, str, list[Path]]:
        private, keys = _keypair()
        monkeypatch.setattr("connector_agent.update_keys.TRUSTED_KEYS", keys)
        info = up.UpdateInfo(NAME, "0.2.250", "0" * 64, 1)
        if signed:
            info = _signed(private, info)

        def _check(*_a: object, **_k: object) -> up.UpdateInfo:
            return info

        monkeypatch.setattr(up, "check", _check)
        return TestCommand()._run(tmp_path, monkeypatch, capsys, *args, check=False)  # pyright: ignore[reportPrivateUsage]

    def test_an_unsigned_package_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, text, launched = self._run(tmp_path, monkeypatch, capsys, "--ja", signed=False)
        assert code == 1
        assert launched == []
        assert "nicht signiert" in text

    def test_by_hand_it_can_be_forced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _text, launched = self._run(
            tmp_path, monkeypatch, capsys, "--ja", "--ohne-signatur", signed=False
        )
        assert code == 0
        assert len(launched) == 1

    def test_a_signed_package_is_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, text, launched = self._run(tmp_path, monkeypatch, capsys, "--ja", signed=True)
        assert code == 0
        assert len(launched) == 1
        assert "Signatur:     gültig" in text
