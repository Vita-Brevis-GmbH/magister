"""``magister-connector check``: AD-Zeile, Dienst-Umgebung, keine Geheimnisse.

Der Befehl ist der Abnahmebefehl beim Kunden. Er muss das AD mit **denselben**
Zugangsdaten prüfen, die der Dienst bekommt — und darf dabei keinen davon
ausgeben, auch nicht im Fehlerfall.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from connector_agent import cli
from connector_agent.adenv import ServiceEnvironment, apply_missing, parse_env_lines
from connector_agent.config import AgentConfig
from connector_agent.diagnose import ProbeResult

GEHEIM = "S3hr-geheim!"


class _FakeAd:
    def __init__(self, ok: bool, reason: str) -> None:
        self.result = (ok, reason)

    async def probe_service_connection_detailed(self) -> tuple[bool, str]:
        return self.result


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "https://172.25.12.10:46200",
                "state_dir": str(tmp_path / "state"),
                "ca_bundle": str(tmp_path / "ca.pem"),
                "allowed_ous": ["OU=Schule,DC=x,DC=y"],
            }
        )
    )
    return path


def _run_check(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config_file: Path,
    *,
    ad: Any,
    service: ServiceEnvironment | None,
    probe: ProbeResult,
) -> tuple[int, str]:
    monkeypatch.setattr(cli, "service_environment", lambda: service)
    monkeypatch.setattr(cli, "build_ad_client", lambda: ad)

    def _probe(_config: AgentConfig) -> ProbeResult:
        return probe

    monkeypatch.setattr(cli, "probe_channel", _probe)
    for key in ("MAGISTER_AD_DCS", "MAGISTER_AD_BIND_DN", "MAGISTER_AD_BIND_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    code = cli.main(["--config", str(config_file), "check"])
    out = capsys.readouterr()
    return code, out.out + out.err


class TestAdLine:
    def test_a_rejected_bind_is_named_without_the_password(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        service = ServiceEnvironment(
            source="/etc/magister-connector/ad.env",
            values={
                "MAGISTER_AD_DCS": "dc01.schule.local",
                "MAGISTER_AD_BIND_DN": "CN=svc,DC=schule,DC=local",
                "MAGISTER_AD_BIND_PASSWORD": GEHEIM,
            },
        )
        code, text = _run_check(
            monkeypatch,
            capsys,
            config_file,
            ad=_FakeAd(False, "ad_auth"),
            service=service,
            probe=ProbeResult(True, "ok"),
        )
        assert code == 1
        assert "AD:           FEHLER" in text
        assert "Dienstkonto abgewiesen" in text
        assert "/etc/magister-connector/ad.env, 3 Wert(e)" in text
        assert GEHEIM not in text

    def test_a_working_bind_is_ok(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        config_file: Path,
    ) -> None:
        _code, text = _run_check(
            monkeypatch,
            capsys,
            config_file,
            ad=_FakeAd(True, "ad_ok"),
            service=None,
            probe=ProbeResult(True, "ok"),
        )
        assert "AD:           ok" in text
        assert "keine Dienst-Umgebung gefunden" in text

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
            service=None,
            probe=ProbeResult(False, "Zertifikat passt nicht"),
        )
        assert code == 1
        assert "WARNUNG — Der Endpunkt nennt die IP-Adresse 172.25.12.10" in text
        assert "Kanal:        FEHLER — Zertifikat passt nicht" in text


class TestServiceEnvironment:
    def test_parses_like_systemd(self) -> None:
        values = parse_env_lines(
            [
                "# Kommentar",
                "",
                "MAGISTER_AD_DCS=dc01.schule.local,dc02.schule.local",
                'MAGISTER_AD_BIND_PASSWORD="mit = Gleichheitszeichen"',
                "PATH=/nicht/unseres",
                "kaputt",
            ]
        )
        assert values == {
            "MAGISTER_AD_DCS": "dc01.schule.local,dc02.schule.local",
            "MAGISTER_AD_BIND_PASSWORD": "mit = Gleichheitszeichen",
        }

    def test_values_set_by_hand_win(self) -> None:
        env = {"MAGISTER_AD_DCS": "von-hand"}
        service = ServiceEnvironment(
            source="x", values={"MAGISTER_AD_DCS": "dienst", "MAGISTER_AD_BIND_DN": "dn"}
        )
        assert apply_missing(service, env) == ["MAGISTER_AD_BIND_DN"]
        assert env == {"MAGISTER_AD_DCS": "von-hand", "MAGISTER_AD_BIND_DN": "dn"}


class TestBuildAdClientKeepsSecretsOut:
    def test_a_validation_error_names_fields_not_values(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pytest.importorskip("magister_api.config")
        monkeypatch.setenv("MAGISTER_AD_BIND_PASSWORD", GEHEIM)
        # Ein Feld, das sicher scheitert: eine Zahl, die keine ist.
        monkeypatch.setenv("MAGISTER_AD_SYNC_INTERVAL_MINUTES", "keine-zahl")
        result = cli.build_ad_client()
        err = capsys.readouterr().err
        if result is not None:
            pytest.skip("Die AD-Schicht kennt das Feld nicht; nichts zu prüfen.")
        assert GEHEIM not in err
        assert "keine-zahl" not in err
