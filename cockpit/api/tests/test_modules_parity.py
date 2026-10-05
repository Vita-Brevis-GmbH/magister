"""Konsole und Datenebene kennen dieselben Module (ADR-0008, ADR-0017).

Der Katalog steht zweimal: in ``cockpit_api/services/modules.py`` und in
``apps/api/magister_api/modules/catalog.py``. Die Konsole importiert die
Datenebene nicht — also wird hier deren Datei geladen und verglichen. Ein
neues Modul in der Datenebene ohne Eintrag hier hiesse: die Konsole weist
einen Schalter dafür ab, den der Kunde haben dürfte.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from cockpit_api.services.modules import KNOWN_PROFILES, MODULES, effective


def _load_catalog() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "api"
        / "magister_api"
        / "modules"
        / "catalog.py"
    )
    if not path.is_file():
        pytest.skip(f"Katalog der Datenebene nicht gefunden: {path}")
    spec = importlib.util.spec_from_file_location("dataplane_catalog", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses löst Annotationen über sys.modules auf.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


catalog = _load_catalog()


def test_same_profiles() -> None:
    assert tuple(catalog.KNOWN_PROFILES) == KNOWN_PROFILES


def test_same_modules_same_policy() -> None:
    theirs = {
        m.id: (m.toggleable, tuple(sorted(m.default_in_profiles))) for m in catalog.MODULE_CATALOG
    }
    ours = {m.id: (m.toggleable, tuple(sorted(m.default_in_profiles))) for m in MODULES}
    assert ours == theirs


@pytest.mark.parametrize("profile", KNOWN_PROFILES)
@pytest.mark.parametrize(
    "overrides", [{}, {"devices": False}, {"departments": True, "classes": False}]
)
def test_same_effective_set(profile: str, overrides: dict[str, bool]) -> None:
    ours = {k for k, on in effective(profile, overrides).items() if on}
    assert ours == set(catalog.effective_enabled_ids(profile, overrides))
