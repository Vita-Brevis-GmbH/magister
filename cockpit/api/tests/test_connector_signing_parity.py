"""Agent und Konsole müssen dieselbe HMAC rechnen (ADR-0014).

Die Berechnung steht zweimal im Repository: einmal in der Konsole
(``cockpit_api/services/connector.py``) und einmal im Agenten
(``agent/connector_agent/signing.py``). Das ist Absicht — der Agent ist ein
eigenständiges Paket beim Kunden und soll die Konsole nicht importieren.

Zwei Implementierungen derselben Regel driften aber, und zwar leise: die
Signatur passt dann für die meisten Eingaben und für manche nicht. Ein Fehler,
der nur bei Umlauten oder bei einer bestimmten Schlüsselreihenfolge auftritt,
kostet einen halben Tag Suche. Deshalb wird hier die Datei des Agenten geladen
und beide Wege mit denselben Eingaben verglichen.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from cockpit_api.services.connector import (
    canonical_result_body as console_body,
)
from cockpit_api.services.connector import (
    sign_result as console_sign,
)


def _load_agent_signing() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "agent" / "connector_agent" / "signing.py"
    if not path.is_file():
        pytest.skip(f"Agent-Modul nicht gefunden: {path}")
    spec = importlib.util.spec_from_file_location("agent_signing", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent = _load_agent_signing()

CASES: list[dict[str, Any]] = [
    {"ok": True, "result": None, "error": None},
    {"ok": False, "result": None, "error": "RuntimeError"},
    {"ok": True, "result": "CN=Muster Hans,OU=Lehrer,DC=x", "error": None},
    {"ok": True, "result": [True, "ok"], "error": None},
    # Schlüsselreihenfolge absichtlich verdreht: sort_keys muss sie
    # vereinheitlichen, sonst hängt die Signatur von der Einfügereihenfolge ab.
    {"ok": True, "result": {"z": 1, "a": 2, "m": [3, {"y": 4, "b": 5}]}, "error": None},
    # Umlaute: ensure_ascii=False auf beiden Seiten, sonst sind es andere Bytes.
    {"ok": True, "result": {"name": "Müller-Lüthi", "ou": "Schule Bümpliz"}, "error": None},
    {"ok": False, "result": None, "error": "Domänen-Admins abgelehnt"},
    {"ok": True, "result": {"leer": "", "null": None, "false": False, "zero": 0}, "error": None},
]


@pytest.mark.parametrize("case", CASES, ids=range(len(CASES)))
def test_the_canonical_body_is_byte_identical(case: dict[str, Any]) -> None:
    mine = console_body(ok=case["ok"], result=case["result"], error=case["error"])
    theirs = agent.canonical_result_body(ok=case["ok"], result=case["result"], error=case["error"])
    assert mine == theirs


@pytest.mark.parametrize("case", CASES, ids=range(len(CASES)))
def test_the_signature_is_identical(case: dict[str, Any]) -> None:
    body = console_body(ok=case["ok"], result=case["result"], error=case["error"])
    job_id = "7f000000-0000-0000-0000-000000000001"
    key = "gemeinsamer-hmac-schluessel"
    assert console_sign(key, job_id, body) == agent.sign_result(key, job_id, body)


def test_the_job_id_changes_the_signature_on_both_sides() -> None:
    """Die Auftrags-Id gehört in die Signatur.

    Sonst liesse sich ein gültig signiertes Ergebnis von einem Auftrag auf
    einen anderen umhängen — und beide Seiten müssen das gleich sehen.
    """
    body = console_body(ok=True, result=None, error=None)
    key = "k"
    a_console = console_sign(key, "job-a", body)
    b_console = console_sign(key, "job-b", body)
    assert a_console != b_console
    assert agent.sign_result(key, "job-a", body) == a_console
    assert agent.sign_result(key, "job-b", body) == b_console
