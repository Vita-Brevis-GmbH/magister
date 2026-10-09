"""``magister-connector update``: prüfen, laden, Prüfsumme, einspielen.

Der Agent aktualisiert sich nie von selbst — ein Mensch auf dem DC ruft den
Befehl auf. Geprüft wird hier, dass er nur Neueres nimmt, nur eine Datei mit
stimmender Prüfsumme behält und das Einspielen so anstösst, dass der Dienst
danach wieder läuft.
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
        assert 'msiexec /i "C:\\Daten\\x.msi" /qn /norestart /l*v "C:\\Daten\\x.log"' in script
        assert script.index("msiexec") < script.index("sc start MagisterConnector")
        assert "\r\n" in script

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

        def _launch(msi: Path) -> Path:
            launched.append(msi)
            return msi.with_suffix(".log")

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
