"""Der Agent auf dem DC im Betrieb: Fassung, Start ohne Cockpit, Eingrenzung, Dienst.

Was hier steht, ist am echten DC aufgefallen oder hätte es können:

* jedes MSI hiess „0.2.0“ — auf dem DC war nicht zu sehen, was läuft;
* ein Neustart des DC, während die Plattform kurz weg ist, darf den Agenten
  nicht lahmlegen;
* eine Such-Basis über der Freigabe (``DC=…``) liess den Abgleich scheitern.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from connector_agent import cli
from connector_agent import remote as remote_cfg
from connector_agent.config import AgentConfig, AgentSecrets
from connector_agent.guardrails import Guardrails

SCHULE = "OU=Schule,OU=Magister,DC=gemeinde,DC=local"
VERWALTUNG = "OU=Verwaltung,OU=Magister,DC=gemeinde,DC=local"
SECRETS = AgentSecrets(agent_id="a", api_key="k", result_hmac_key="h", spki_sha256="f")


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig.from_mapping(
        {"endpoint": "https://connect.magister.test:46200", "state_dir": str(tmp_path)}
    )


class TestBuildVersion:
    def test_without_a_build_file_the_base_version_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delitem(sys.modules, "connector_agent._build", raising=False)

        def _missing(name: str) -> types.ModuleType:
            raise ImportError(name)

        monkeypatch.setattr("importlib.import_module", _missing)
        assert cli.build_info() == (cli.BASE_VERSION, "")

    def test_the_build_file_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = types.ModuleType("connector_agent._build")
        module.BUILD_VERSION = "0.2.199"  # type: ignore[attr-defined]
        module.BUILD_COMMIT = "abc1234"  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "connector_agent._build", module)
        assert cli.build_info() == ("0.2.199", "abc1234")

    def test_the_build_script_counts_commits(self) -> None:
        """Die dritte Stelle wächst mit jedem Commit und passt in Windows Installer."""
        import importlib.util

        path = Path(__file__).resolve().parents[1] / "packaging" / "bau_fassung.py"
        spec = importlib.util.spec_from_file_location("bau_fassung", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fassung: Any = getattr(module, "fassung")  # noqa: B009
        version, commit = cast(tuple[str, str], fassung())
        major, minor, patch = (int(p) for p in str(version).split("."))
        assert (major, minor) == tuple(int(p) for p in cli.BASE_VERSION.split(".")[:2])
        assert 1 <= patch <= 65535
        assert re.fullmatch(r"[0-9a-f]{7,12}", str(commit))


class TestStartWithoutTheCockpit:
    def test_fresh_config_is_cached(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = {"allowed_ous": [SCHULE], "revision": "r1"}

        def _fetch(*_a: Any, **_k: Any) -> tuple[remote_cfg.RemoteConfig, dict[str, Any]]:
            return remote_cfg.parse(raw), raw

        monkeypatch.setattr(remote_cfg, "fetch_sync", _fetch)
        config = _config(tmp_path)
        remote = cli.initial_remote(config, SECRETS)
        assert remote.allowed_ous == frozenset({SCHULE})
        cached = json.loads(remote_cfg.cache_path(config).read_text(encoding="utf-8"))
        assert cached["revision"] == "r1"

    def test_the_last_config_carries_a_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plattform kurz weg, DC startet neu: der Agent arbeitet mit der letzten Fassung."""
        config = _config(tmp_path)
        remote_cfg.save_cache(config, {"allowed_ous": [SCHULE], "revision": "r1"})

        def _fail(*_a: Any, **_k: Any) -> Any:
            raise remote_cfg.RemoteConfigError("Konfiguration nicht geholt (HTTP 503).")

        monkeypatch.setattr(remote_cfg, "fetch_sync", _fail)
        remote = cli.initial_remote(config, SECRETS)
        assert remote.revision == "r1"

    def test_without_cockpit_and_cache_it_does_not_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(*_a: Any, **_k: Any) -> Any:
            raise remote_cfg.RemoteConfigError("weg")

        monkeypatch.setattr(remote_cfg, "fetch_sync", _fail)
        with pytest.raises(remote_cfg.RemoteConfigError, match="keine frühere Fassung"):
            cli.initial_remote(_config(tmp_path), SECRETS)

    def test_the_cache_keeps_its_own_checks(self, tmp_path: Path) -> None:
        """Auch aus dem Zwischenspeicher: eine verbotene Freigabe gilt nicht."""
        config = _config(tmp_path)
        remote_cfg.save_cache(
            config, {"allowed_ous": ["OU=Domain Controllers,DC=gemeinde,DC=local", SCHULE]}
        )
        cached = remote_cfg.load_cache(config)
        assert cached is not None
        assert cached.allowed_ous == frozenset({SCHULE})

    def test_a_broken_cache_is_no_cache(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        remote_cfg.cache_path(config).write_text("{kaputt", encoding="utf-8")
        assert remote_cfg.load_cache(config) is None


class TestSearchBaseNarrowing:
    def _rails(self) -> Guardrails:
        return Guardrails(allowed_ous=frozenset({SCHULE, VERWALTUNG}))

    def test_a_base_inside_the_approval_stays(self) -> None:
        base = f"OU=Lehrer,{SCHULE}"
        assert self._rails().narrow_search_base(base) == [base]

    def test_a_base_above_becomes_the_approved_ous_below_it(self) -> None:
        assert self._rails().narrow_search_base("DC=gemeinde,DC=local") == sorted(
            [SCHULE, VERWALTUNG]
        )
        assert self._rails().narrow_search_base("ou=magister, dc=gemeinde, dc=local") == sorted(
            [SCHULE, VERWALTUNG]
        )

    def test_a_base_beside_stays_and_is_refused_later(self) -> None:
        base = "OU=Fremd,DC=gemeinde,DC=local"
        assert self._rails().narrow_search_base(base) == [base]

    def test_nothing_approved_means_nothing_widened(self) -> None:
        base = "DC=gemeinde,DC=local"
        assert Guardrails().narrow_search_base(base) == [base]


class TestService:
    def test_starting_is_a_windows_matter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from connector_agent import uninstall

        monkeypatch.setattr(uninstall, "IS_WINDOWS", False)
        assert "Windows" in uninstall.start_service()

    def test_enroll_does_not_start_when_asked_not_to(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from connector_agent import uninstall

        started: list[bool] = []
        monkeypatch.setattr(uninstall, "start_service", lambda: started.append(True) or "x")

        def _enroll(config: AgentConfig, **_kw: Any) -> Any:
            raise cli.EnrollmentFailedError("Testende")

        monkeypatch.setattr(cli, "enroll", _enroll)
        code = cli.main(
            [
                "--config",
                str(tmp_path / "config.json"),
                "enroll",
                "--endpoint",
                "https://connect.magister.test:46200",
                "--token",
                "t",
                "--ohne-start",
            ]
        )
        assert code == 1
        assert started == []
