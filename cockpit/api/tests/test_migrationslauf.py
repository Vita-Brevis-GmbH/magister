"""Kann `alembic` die Konsole überhaupt migrieren — auch dort, wo sie nur
einkopiert ist?

Der Fehler, den diese Datei festnagelt, trat beim ersten Aufbau der
Plattform auf und legte ihn sofort still:

    File "/app/alembic/env.py", line 9, in <module>
        from cockpit_api.config import settings
    ModuleNotFoundError: No module named 'cockpit_api'

In der Entwicklung ist die Konsole als Paket installiert, und der Import
gelingt. Im Container ist sie nur nach `/app/cockpit_api` kopiert — dann
muss das Arbeitsverzeichnis auf dem Suchpfad stehen, und genau dafür gibt
es `prepend_sys_path` in `alembic.ini`. Die Datenebene hat die Zeile seit
jeher; der Konsole fehlte sie.

Geprüft wird die Zeile und nicht der Lauf: ein echter Lauf bräuchte eine
Umgebung, in der das Paket NICHT installiert ist — und das ist genau die
Umgebung, die es in der CI nicht gibt. Die Zeile ist die Ursache, und ihr
Fehlen ist der ganze Fehler.
"""

from __future__ import annotations

import configparser
from pathlib import Path


def test_alembic_findet_das_paket_auch_wenn_es_nur_daneben_liegt() -> None:
    ini = configparser.ConfigParser()
    ini.read(Path(__file__).resolve().parents[1] / "alembic.ini")
    assert ini.get("alembic", "prepend_sys_path", fallback="") == ".", (
        "alembic.ini braucht `prepend_sys_path = .` — sonst scheitert "
        "`alembic upgrade head` im Container mit ModuleNotFoundError."
    )
