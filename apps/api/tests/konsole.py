"""Wo der Checkout von vitabrevis-cockpit liegt, gegen den die Abgleichstests prüfen.

Bis PR #60 lag die Konsole in diesem Repo (`cockpit/`), und die Tests fanden
sie vier Ordner höher. Seither lebt sie im Repo `vitabrevis-cockpit`, und die
Tests suchen einen eigenen Checkout in dieser Reihenfolge:

1. `MAGISTER_TEST_KONSOLE_DIR` (Wurzel des Checkouts). Ist die Variable
   gesetzt, gilt nur sie, ohne Rückfall auf die Punkte 2 und 3;
2. ein Ordner `vitabrevis-cockpit` in diesem Repo (so legt ihn die CI ab,
   gitignored);
3. ein Ordner `vitabrevis-cockpit` neben diesem Repo. Auf dem Host
   (`/opt/cockpit/src` neben `/opt/magister`) passt das nicht, dort gilt
   Punkt 1.

Fehlt er, überspringen sich die betroffenen Tests mit dem gesuchten Pfad in
der Meldung; die CI sagt das zusätzlich in der Zusammenfassung
(`docs/runbooks/ci-cockpit.md`). Gegenstück im Cockpit:
`api/tests/magister_pfad.py`.

Gelesen wird die Datei der Konsole, nicht importiert: die Datenebene hängt
nicht von `cockpit_api` ab und umgekehrt.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# tests -> api -> apps -> Wurzel des Repos
REPO = Path(__file__).resolve().parents[3]


def konsole_root() -> Path | None:
    """Wurzel des Cockpit-Checkouts oder `None`."""
    aus_umgebung = os.environ.get("MAGISTER_TEST_KONSOLE_DIR", "").strip()
    kandidaten = (
        [Path(aus_umgebung)]
        if aus_umgebung
        else [REPO / "vitabrevis-cockpit", REPO.parent / "vitabrevis-cockpit"]
    )
    for kandidat in kandidaten:
        if (kandidat / "api" / "cockpit_api").is_dir():
            return kandidat
    return None


def konsole_datei(*teile: str) -> Path | None:
    """Eine Datei unter `api/cockpit_api/` der Konsole, wenn es sie gibt."""
    root = konsole_root()
    if root is None:
        return None
    pfad = root.joinpath("api", "cockpit_api", *teile)
    return pfad if pfad.is_file() else None


def konsole_datei_oder_skip(*teile: str) -> Path:
    """Wie `konsole_datei`; fehlt sie, wird der Test übersprungen."""
    pfad = konsole_datei(*teile)
    if pfad is None:
        gesucht = Path(
            os.environ.get("MAGISTER_TEST_KONSOLE_DIR", "").strip()
            or REPO / "vitabrevis-cockpit"
        ).joinpath("api", "cockpit_api", *teile)
        pytest.skip(
            f"Konsole nicht gefunden: {gesucht} "
            "(MAGISTER_TEST_KONSOLE_DIR, docs/runbooks/ci-cockpit.md)"
        )
    return pfad
