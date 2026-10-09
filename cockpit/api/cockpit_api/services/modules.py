"""Modulkatalog der Datenebene, wie die Konsole ihn braucht (ADR-0008, ADR-0017).

Gehostet ist die Konsole der einzige Autor von Profil und Modul-Schaltern
eines Kunden; der Abgleich schreibt sie ins Kundenschema. Damit ein Schalter,
den die Datenebene nicht kennt oder nicht schalten lässt, **hier** abgewiesen
wird und nicht erst beim Kunden verworfen, braucht die Konsole den Katalog.

Er steht zweimal im Repository: hier und in
``apps/api/magister_api/modules/catalog.py``. Das ist Absicht — die Konsole
importiert die Datenebene nicht. ``tests/test_modules_parity.py`` lädt die
Datei der Datenebene und vergleicht; wer dort ein Modul einträgt, sieht den
Test hier rot werden.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

KNOWN_PROFILES: tuple[str, ...] = ("school", "company", "neutral")


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    id: str
    toggleable: bool = True
    default_in_profiles: tuple[str, ...] = ()


MODULES: tuple[ModuleInfo, ...] = (
    ModuleInfo("platform", toggleable=False),
    ModuleInfo("ad", toggleable=False),
    ModuleInfo("users", toggleable=False),
    ModuleInfo("settings", toggleable=False),
    ModuleInfo("templates", default_in_profiles=("school", "company")),
    ModuleInfo("classes", default_in_profiles=("school",)),
    ModuleInfo("imports", default_in_profiles=("school", "company")),
    ModuleInfo("departments", default_in_profiles=("company",)),
    ModuleInfo("reports", default_in_profiles=("school", "company")),
    ModuleInfo("devices", default_in_profiles=("school", "company")),
)

_BY_ID = {m.id: m for m in MODULES}


class ModuleSettingsError(ValueError):
    """Ein Profil oder Modul-Schalter, den die Datenebene nicht annehmen würde."""


def check_profile(value: Any) -> str:
    if value not in KNOWN_PROFILES:
        raise ModuleSettingsError(
            f"'instance_profile' muss eines von {', '.join(KNOWN_PROFILES)} sein, nicht {value!r}."
        )
    return str(value)


def check_overrides(value: Any) -> dict[str, bool]:
    """Prüft ``module_overrides``: bekannte, schaltbare Module, Wert true/false."""
    if not isinstance(value, dict):
        raise ModuleSettingsError("'module_overrides' muss ein Objekt {modul: true|false} sein.")
    out: dict[str, bool] = {}
    items = cast(dict[object, object], value).items()
    for key, on in items:
        module = _BY_ID.get(str(key))
        if module is None:
            raise ModuleSettingsError(
                f"'module_overrides': '{key}' ist kein Modul. Bekannt sind: "
                f"{', '.join(m.id for m in MODULES if m.toggleable)}."
            )
        if not module.toggleable:
            raise ModuleSettingsError(
                f"'module_overrides': '{key}' gehört zur Basis und lässt sich nicht schalten."
            )
        if not isinstance(on, bool):
            raise ModuleSettingsError(f"'module_overrides': '{key}' erwartet true oder false.")
        out[str(key)] = on
    return out


def effective(profile: str, overrides: Mapping[str, bool]) -> dict[str, bool]:
    """{modul: an?} — dieselbe Regel wie ``catalog.effective_enabled_ids``."""
    result: dict[str, bool] = {}
    for module in MODULES:
        if not module.toggleable:
            result[module.id] = True
        elif module.id in overrides:
            result[module.id] = bool(overrides[module.id])
        else:
            result[module.id] = profile in module.default_in_profiles
    return result


__all__ = [
    "KNOWN_PROFILES",
    "MODULES",
    "ModuleInfo",
    "ModuleSettingsError",
    "check_overrides",
    "check_profile",
    "effective",
]
