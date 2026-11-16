"""Fremde Rollen entziehen lassen: ``role_revocations`` im Soll-Zustand (ADR-0027).

* fehlt das Feld oder ist es `null`, wird nichts entzogen;
* ein Eintrag nennt Person (GUID) und Rolle; die GUID wird klein geschrieben,
  zusätzliche Felder werden übergangen, doppelte zählen einmal;
* eine falsche Form ist ein Fehler im Soll-Zustand (der letzte gute Stand
  bleibt) — und die Meldung nennt den eingereichten Wert nicht.
"""

from __future__ import annotations

from typing import Any

import pytest

from magister_api.tenancy.desired_state import (
    DesiredRoleRevocation,
    DesiredStateUnavailableError,
    parse_desired_state,
)

GUID = "8a1f0a52-5c1d-5d7e-9a7f-000000000001"


def _state(revocations: Any) -> dict[str, Any]:
    return {"settings": {}, "role_assignments": [], "role_revocations": revocations}


class TestParse:
    def test_missing_or_null_revokes_nothing(self) -> None:
        assert parse_desired_state({"settings": {}}).role_revocations == ()
        assert parse_desired_state(_state(None)).role_revocations == ()
        assert parse_desired_state(_state([])).role_revocations == ()

    def test_a_valid_list(self) -> None:
        state = parse_desired_state(
            _state(
                [
                    {"principal": GUID.upper(), "role": "admin"},
                    {"principal": f"{{{GUID}}}", "role": "schulleitung", "username": "anna"},
                    {"principal": GUID, "role": "eigene_rolle-2"},
                    {"principal": GUID, "role": "admin"},
                ]
            )
        )
        assert state.role_revocations == (
            DesiredRoleRevocation(GUID, "admin"),
            DesiredRoleRevocation(GUID, "schulleitung"),
            DesiredRoleRevocation(GUID, "eigene_rolle-2"),
        )

    @pytest.mark.parametrize(
        "revocations",
        [
            "admin",
            [GUID],
            [{"principal": GUID}],
            [{"role": "admin"}],
            [{"principal": 7, "role": "admin"}],
            [{"principal": GUID, "role": "Admin"}],
            [{"principal": GUID, "role": ""}],
            [{"principal": GUID, "role": "x" * 33}],
            [{"principal": "keine-guid", "role": "admin"}],
        ],
    )
    def test_a_wrong_form_is_an_error(self, revocations: Any) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(_state(revocations))

    def test_the_error_does_not_echo_the_value(self) -> None:
        with pytest.raises(DesiredStateUnavailableError) as exc:
            parse_desired_state(_state([{"principal": "geheim-name@example.ch", "role": "smi"}]))
        assert "geheim-name" not in str(exc.value)
