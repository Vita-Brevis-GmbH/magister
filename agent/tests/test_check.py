"""``magister-connector check``: Kanal, Konfiguration aus dem Cockpit, AD.

Der Befehl ist der Abnahmebefehl auf dem DC. Er prüft das AD mit **derselben**
Konfiguration, die der Dienst aus dem Cockpit holt — Kerberos als
Maschinenkonto, kein Passwort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from connector_agent import cli
from connector_agent import remote as remote_cfg
from connector_agent.config import AgentConfig, AgentSecrets
from connector_agent.diagnose import ProbeResult


class _FakeAd:
    def __init__(self, ok: bool, reason: str) -> None:
        self.result = (ok, reason)

    async def probe_service_connection_detailed(self) -> tuple[bool, str]:
        return self.result


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    (state / "secrets.json").write_text(
        json.dumps({"agent_id": "a", "api_key": "k", "result_hmac_key": "h", "spki_sha256": "abc"})
    )
    (state / "secrets.json").chmod(0o600)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "https://172.25.12.10:46200",
                "state_dir": str(state),
                "ca_bundle": str(tmp_path / "ca.pem"),
            }
        )
    )
    return path


REMOTE: dict[str, Any] = {
    "allowed_ous": ["OU=Schule,DC=x,DC=y"],
    "protected_groups": [],
    "ad": {"dcs": ["dc01.x.y"], "users_search_base": "OU=Schule,DC=x,DC=y"},
    "poll_seconds": 25,
    "revision": "r1",
}


def _run_check(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config_file: Path,
    *,
    ad: Any,
    probe: ProbeResult,
    remote: dict[str, Any] | None = REMOTE,
) -> tuple[int, str]:
    def _ad(_remote: remote_cfg.RemoteConfig) -> Any:
        return ad

    def _cert(_config: AgentConfig) -> int:
        return 0

    monkeypatch.setattr(cli, "build_ad_client", _ad)
    monkeypatch.setattr(cli, "_report_certificate", _cert)

    def _probe(_config: AgentConfig) -> ProbeResult:
        return probe

    def _fetch(
        _config: AgentConfig, _secrets: AgentSecrets, **_kw: Any
    ) -> tuple[remote_cfg.RemoteConfig, dict[str, Any]]:
        if remote is None:
            raise remote_cfg.RemoteConfigError("Konfiguration nicht geholt (HTTP 503).")
        return remote_cfg.parse(remote), remote

    monkeypatch.setattr(cli, "probe_channel", _probe)
    monkeypatch.setattr(remote_cfg, "fetch_sync", _fetch)
    code = cli.main(["--config", str(config_file), "check"])
    out = capsys.readouterr()
    return code, out.out + out.err


class TestCheck:
    def test_all_green(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        _code, text = _run_check(
            monkeypatch, capsys, config_file, ad=_FakeAd(True, "ad_ok"), probe=ProbeResult(True, "")
        )
        assert "Cockpit:      ok — Konfiguration r1" in text
        assert "OU-Freigabe:  1 OU(s) aus dem Cockpit" in text
        assert "DC:           dc01.x.y" in text
        assert "AD:           ok — LDAPS mit Kerberos-Anmeldung gelungen" in text

    def test_a_rejected_kerberos_bind_is_explained(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        code, text = _run_check(
            monkeypatch,
            capsys,
            config_file,
            ad=_FakeAd(False, "ad_auth"),
            probe=ProbeResult(True, ""),
        )
        assert code == 1
        assert "Kerberos-Anmeldung als Maschinenkonto" in text

    def test_a_forbidden_ou_from_the_cockpit_is_shown_as_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        remote = {**REMOTE, "allowed_ous": ["OU=Domain Controllers,DC=x,DC=y"]}
        code, text = _run_check(
            monkeypatch,
            capsys,
            config_file,
            ad=_FakeAd(True, "ad_ok"),
            probe=ProbeResult(True, ""),
            remote=remote,
        )
        assert code == 1
        assert "OU-Freigabe:  LEER" in text
        assert "VERWORFEN (liegt in ou=domain controllers)" in text

    def test_without_the_cockpit_the_cached_config_is_used(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        config = AgentConfig.from_file(config_file)
        remote_cfg.save_cache(config, REMOTE)
        code, text = _run_check(
            monkeypatch,
            capsys,
            config_file,
            ad=_FakeAd(True, "ad_ok"),
            probe=ProbeResult(True, ""),
            remote=None,
        )
        assert code == 1
        assert "es gilt die zuletzt geholte" in text
        assert "OU-Freigabe:  1 OU(s)" in text

    def test_ip_endpoint_and_failed_channel_are_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        code, text = _run_check(
            monkeypatch,
            capsys,
            config_file,
            ad=_FakeAd(True, "ad_ok"),
            probe=ProbeResult(False, "Zertifikat passt nicht"),
        )
        assert code == 1
        assert "WARNUNG — Der Endpunkt nennt die IP-Adresse 172.25.12.10" in text
        assert "Kanal:        FEHLER — Zertifikat passt nicht" in text


class TestRemoteConfig:
    def test_the_ad_settings_are_kerberos_without_a_password(self) -> None:
        kwargs = remote_cfg.ad_settings_kwargs(remote_cfg.parse(REMOTE))
        assert kwargs["ad_bind_mode"] == "gssapi"
        assert kwargs["ad_bind_password"] is None
        assert kwargs["ad_dcs"] == ["dc01.x.y"]

    def test_without_dcs_the_agent_uses_its_own_server(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(remote_cfg, "local_dc_fqdn", lambda: "dc07.x.y")
        kwargs = remote_cfg.ad_settings_kwargs(remote_cfg.parse({**REMOTE, "ad": {}}))
        assert kwargs["ad_dcs"] == ["dc07.x.y"]

    @pytest.mark.parametrize(
        "dn",
        [
            "DC=x,DC=y",
            "OU=Domain Controllers,DC=x,DC=y",
            "OU=Sub,CN=System,DC=x,DC=y",
            "CN=Builtin,DC=x,DC=y",
            "OU=ohne-domaene",
            "kein dn",
        ],
    )
    def test_forbidden_bases_are_dropped(self, dn: str) -> None:
        parsed = remote_cfg.parse({"allowed_ous": [dn, "OU=Schule,DC=x,DC=y"]})
        assert parsed.allowed_ous == frozenset({"OU=Schule,DC=x,DC=y"})
        assert [d for d, _ in parsed.refused_ous] == [dn]

    def test_the_built_ad_client_is_kerberos(self) -> None:
        pytest.importorskip("magister_api.config")
        client = cli.build_ad_client(remote_cfg.parse(REMOTE))
        assert client is not None
        settings: Any = getattr(client, "_settings")  # noqa: B009
        mode: str = settings.ad_bind_mode
        dcs: list[str] = settings.ad_dcs
        assert mode == "gssapi"
        assert dcs == ["dc01.x.y"]

    def test_legacy_local_ous_are_ignored(self, caplog: pytest.LogCaptureFixture) -> None:
        config = AgentConfig.from_mapping(
            {"endpoint": "https://connect.example.ch:46200", "allowed_ous": ["OU=A,DC=x"]}
        )
        assert not hasattr(config, "allowed_ous")
        assert "Cockpit" in caplog.text


class TestEnrollWritesTheLocalConfig:
    def test_endpoint_and_ca_land_in_the_state_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ca = tmp_path / "root.pem"
        ca.write_text("-----BEGIN CERTIFICATE-----\n")
        path = tmp_path / "state" / "config.json"
        seen: dict[str, AgentConfig] = {}

        def _enroll(config: AgentConfig, **_kw: Any) -> Any:
            seen["config"] = config
            raise cli.EnrollmentFailedError("Testende")

        monkeypatch.setattr(cli, "enroll", _enroll)
        code = cli.main(
            [
                "--config",
                str(path),
                "enroll",
                "--endpoint",
                "https://connect.example.ch:46200/",
                "--ca",
                str(ca),
                "--token",
                "t",
                "--ohne-start",
            ]
        )
        assert code == 1
        config = seen["config"]
        assert config.endpoint == "https://connect.example.ch:46200"
        assert config.state_dir == tmp_path / "state"
        assert config.ca_bundle == tmp_path / "state" / "platform-ca.pem"
        assert config.ca_bundle.read_text().startswith("-----BEGIN")

    def test_plain_http_is_refused(self, tmp_path: Path) -> None:
        code = cli.main(
            [
                "--config",
                str(tmp_path / "config.json"),
                "enroll",
                "--endpoint",
                "http://connect.example.ch",
                "--token",
                "t",
            ]
        )
        assert code == 1
        assert not (tmp_path / "config.json").exists()
