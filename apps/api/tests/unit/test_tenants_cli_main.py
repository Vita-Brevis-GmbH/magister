"""``python -m magister_api.cli.tenants`` — der Einstieg im Abbild der Datenebene.

``plattform-aufbau.sh up`` migriert damit nach jedem Update die Kundenschemas.
"""

from __future__ import annotations

import argparse

import pytest

from magister_api.cli import tenants


def test_main_dispatches_migrate_with_its_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[argparse.Namespace] = []

    def fake(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    monkeypatch.setattr(tenants, "cmd_migrate", fake)
    rc = tenants.main(["migrate", "--no-dump", "--keep-going", "--only", "hwb", "gmp"])
    assert rc == 0
    assert seen[0].no_dump is True
    assert seen[0].keep_going is True
    assert seen[0].only == ["hwb", "gmp"]


def test_main_passes_the_exit_code_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tenants, "cmd_list", lambda _args: 1)  # pyright: ignore[reportUnknownLambdaType]
    assert tenants.main(["list"]) == 1
