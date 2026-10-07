"""``magister-connector uninstall``: abmelden, Zugang löschen, Programm entfernen."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest

from connector_agent import cli
from connector_agent import uninstall as un
from connector_agent.config import AgentConfig, load_secrets
from tests.test_renewal import enrolled

__all__ = ["enrolled"]


def _answer(status: int) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/connector/decommission"
        assert request.headers["X-Connector-Api-Key"] == "api-key-fuer-den-test"
        return httpx.Response(status)

    return httpx.MockTransport(handle)


class TestDeregister:
    def test_the_platform_accepts(self, enrolled: AgentConfig) -> None:
        secrets = load_secrets(enrolled)
        assert secrets is not None
        un.deregister(enrolled, secrets, transport=_answer(204))

    def test_already_revoked_is_fine(self, enrolled: AgentConfig) -> None:
        """401: die Plattform kennt den Agenten nicht mehr als gültig — Ziel erreicht."""
        secrets = load_secrets(enrolled)
        assert secrets is not None
        un.deregister(enrolled, secrets, transport=_answer(401))

    def test_anything_else_is_reported(self, enrolled: AgentConfig) -> None:
        secrets = load_secrets(enrolled)
        assert secrets is not None
        with pytest.raises(un.DeregisterError, match="500"):
            un.deregister(enrolled, secrets, transport=_answer(500))

    def test_an_unreachable_platform_is_explained(
        self,
        enrolled: AgentConfig,
    ) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        secrets = load_secrets(enrolled)
        assert secrets is not None
        with pytest.raises(un.DeregisterError):
            un.deregister(enrolled, secrets, transport=httpx.MockTransport(refuse))


class TestWipe:
    def test_credentials_go_config_and_log_stay(
        self,
        enrolled: AgentConfig,
    ) -> None:
        config_file = enrolled.state_dir / "config.json"
        config_file.write_text("{}", encoding="utf-8")
        log = enrolled.state_dir / "agent.log"
        log.write_text("…", encoding="utf-8")
        prev = enrolled.key_path.with_name(enrolled.key_path.name + ".prev")
        prev.write_text("alt", encoding="utf-8")

        removed = un.wipe(enrolled, everything=False, config_path=config_file)

        assert not enrolled.key_path.exists()
        assert not enrolled.cert_path.exists()
        assert not enrolled.secrets_path.exists()
        assert not prev.exists()
        assert config_file.exists() and log.exists()
        assert enrolled.key_path in removed

    def test_everything_removes_the_directory(
        self,
        enrolled: AgentConfig,
        tmp_path: Path,
    ) -> None:
        etc = tmp_path / "etc" / "config.json"
        etc.parent.mkdir()
        etc.write_text("{}", encoding="utf-8")
        un.wipe(enrolled, everything=True, config_path=etc)
        assert not enrolled.state_dir.exists()
        assert not etc.exists()


class TestCommand:
    @pytest.fixture
    def quiet(self, monkeypatch: pytest.MonkeyPatch, enrolled: AgentConfig) -> list[str]:
        calls: list[str] = []

        def stop() -> str:
            calls.append("stop")
            return "angehalten"

        def remove(*, keep: bool) -> str:
            calls.append(f"paket:{keep}")
            return "entfernt"

        def load(path: Path) -> AgentConfig:
            return enrolled

        monkeypatch.setattr(un, "is_admin", lambda: True)
        monkeypatch.setattr(un, "stop_service", stop)
        monkeypatch.setattr(un, "remove_package", remove)
        monkeypatch.setattr(cli.AgentConfig, "from_file", load)
        return calls

    def test_without_confirmation_nothing_happens(
        self,
        quiet: list[str],
        enrolled: AgentConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("nein\n"))
        assert cli.main(["uninstall"]) == 1
        assert quiet == []
        assert enrolled.key_path.exists()

    def test_deregisters_before_it_wipes(
        self,
        quiet: list[str],
        enrolled: AgentConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[bool] = []

        def deregister(config: AgentConfig, secrets: object) -> None:
            # Der Schlüssel muss zu diesem Zeitpunkt noch da sein: ohne ihn
            # kann der Agent nicht mehr beweisen, wer er ist.
            seen.append(config.key_path.exists())

        monkeypatch.setattr(un, "deregister", deregister)
        assert cli.main(["uninstall", "--ja"]) == 0
        assert seen == [True]
        assert not enrolled.key_path.exists()
        assert quiet == ["stop", "paket:False"]

    def test_a_failed_deregistration_still_wipes_and_says_so(
        self,
        quiet: list[str],
        enrolled: AgentConfig,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def deregister(config: AgentConfig, secrets: object) -> None:
            raise un.DeregisterError("Plattform nicht erreichbar")

        monkeypatch.setattr(un, "deregister", deregister)
        assert cli.main(["uninstall", "--ja"]) == 2
        out = capsys.readouterr().out
        assert "NICHT abgemeldet" in out
        assert "widerrufen" in out
        assert not enrolled.key_path.exists()


def test_without_admin_rights_nothing_happens(
    enrolled: AgentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(un, "is_admin", lambda: False)
    assert cli.main(["uninstall", "--ja"]) == 1
    assert enrolled.key_path.exists()
