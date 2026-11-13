"""Rollenliste aus dem Cockpit im Soll-Zustand (ADR-0026).

* fehlt das Feld oder ist es `null`, gibt es **keine Aussage**;
* eine Liste ist **vollständig**, auch `[]`;
* eine falsche Form ist ein Fehler im Soll-Zustand — kein Eintrag wird still
  ausgelassen, denn ein fehlender Eintrag hiesse „Rolle zurücknehmen".
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from magister_api.auth.roles import ROLE_ASSIGNMENT_ROLES
from magister_api.tenancy.desired_state import (
    DesiredRoleAssignment,
    DesiredStateUnavailableError,
    parse_desired_state,
)


def _state(role_assignments: Any) -> dict[str, Any]:
    return {"settings": {}, "role_assignments": role_assignments}


class TestParse:
    def test_a_valid_list(self) -> None:
        state = parse_desired_state(
            _state(
                [
                    {"username": "automato-admin", "role": "admin"},
                    {"username": "Person.A@Example.ch", "role": "schulleitung"},
                    {"username": "it-kunde-a", "role": "smi"},
                ]
            )
        )
        assert state.role_assignments == (
            DesiredRoleAssignment("automato-admin", "admin"),
            # dieselbe Regel wie bei der Anmeldung: klein, ohne Rand
            DesiredRoleAssignment("person.a@example.ch", "schulleitung"),
            DesiredRoleAssignment("it-kunde-a", "smi"),
        )

    def test_missing_means_no_statement(self) -> None:
        assert parse_desired_state({"settings": {}}).role_assignments is None

    def test_null_means_no_statement(self) -> None:
        assert parse_desired_state(_state(None)).role_assignments is None

    def test_an_empty_list_is_a_statement(self) -> None:
        """`[]` heisst „niemand" — nicht „nichts gesagt"."""
        assert parse_desired_state(_state([])).role_assignments == ()

    def test_duplicates_count_once(self) -> None:
        state = parse_desired_state(
            _state(
                [
                    {"username": "anna", "role": "smi"},
                    {"username": "ANNA", "role": "smi"},
                    {"username": "anna", "role": "admin"},
                ]
            )
        )
        assert state.role_assignments == (
            DesiredRoleAssignment("anna", "smi"),
            DesiredRoleAssignment("anna", "admin"),
        )

    def test_extra_fields_of_a_newer_cockpit_are_ignored(self) -> None:
        state = parse_desired_state(
            _state([{"username": "anna", "role": "smi", "anzeige": "Anna"}])
        )
        assert state.role_assignments == (DesiredRoleAssignment("anna", "smi"),)

    @pytest.mark.parametrize(
        ("raw", "match"),
        [
            ({"username": "anna", "role": "smi"}, "keine Liste"),
            ("anna:smi", "keine Liste"),
            (["anna"], "kein Objekt"),
            ([{"username": "anna"}], "erwartete Form"),
            ([{"role": "smi"}], "erwartete Form"),
            ([{"username": 7, "role": "smi"}], "erwartete Form"),
            ([{"username": "anna", "role": None}], "erwartete Form"),
            ([{"username": "", "role": "smi"}], "Benutzername"),
            ([{"username": "mit leerzeichen", "role": "smi"}], "Benutzername"),
            ([{"username": "x" * 256, "role": "smi"}], "Benutzername"),
            ([{"username": "anna", "role": "kl"}], "unbekannt"),
            ([{"username": "anna", "role": "Admin"}], "unbekannt"),
            ([{"username": "anna", "role": "leitung"}], "unbekannt"),
        ],
    )
    def test_a_wrong_shape_is_refused(self, raw: Any, match: str) -> None:
        """Nicht „den Rest nehmen": ein ausgelassener Eintrag nähme Rollen weg."""
        with pytest.raises(DesiredStateUnavailableError, match=match):
            parse_desired_state(_state(raw))

    def test_one_bad_entry_refuses_the_whole_state(self) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(
                _state(
                    [
                        {"username": "anna", "role": "smi"},
                        {"username": "bert", "role": "superuser"},
                    ]
                )
            )


class TestTheCockpitSendsThisShape:
    """Gleichlauf mit dem Cockpit (vitabrevis-cockpit, Cockpit ADR 0007 Nachtrag).

    Gelesen wird die Datei, nicht importiert (`tests/konsole.py`). Das Cockpit
    prüft seinerseits, dass seine Rollen ``ROLE_ASSIGNMENT_ROLES`` sind und
    Benutzernamen nach ``validate_login_name`` gelten (`test_rollen_parity.py`).
    """

    def test_role_keys_and_entry_fields(self) -> None:
        from tests.konsole import konsole_datei_oder_skip

        tree = ast.parse(
            Path(konsole_datei_oder_skip("services", "magister_anmeldung.py")).read_text(
                encoding="utf-8"
            )
        )
        rollen = _dict_keys(tree, "ROLLEN")
        if rollen is None:
            pytest.fail("ROLLEN in der Konsole nicht gefunden (services/magister_anmeldung.py)")
        assert _resolve(tree, rollen) == set(ROLE_ASSIGNMENT_ROLES)

        fields = _returned_dict_keys(tree, "rollen_fuer_magister")
        assert fields == {"username", "role"}

    def test_the_desired_state_carries_the_list(self) -> None:
        from tests.konsole import konsole_datei_oder_skip

        source = Path(konsole_datei_oder_skip("services", "settings.py")).read_text(
            encoding="utf-8"
        )
        assert '"role_assignments"' in source


def _dict_keys(tree: ast.Module, name: str) -> list[ast.expr] | None:
    for node in ast.walk(tree):
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == name:
            value = node.value if isinstance(node, ast.AnnAssign) else None
            if isinstance(value, ast.Dict):
                return [k for k in value.keys if k is not None]
    return None


def _resolve(tree: ast.Module, keys: list[ast.expr]) -> set[str]:
    """Schlüssel als Text — auch über einen Modulnamen wie ``ADMIN = "admin"``."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value.value, str):
                    constants[target.id] = node.value.value
    out: set[str] = set()
    for key in keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            out.add(key.value)
        elif isinstance(key, ast.Name) and key.id in constants:
            out.add(constants[key.id])
    return out


def _returned_dict_keys(tree: ast.Module, function: str) -> set[str] | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    return {
                        k.value
                        for k in inner.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    return None
