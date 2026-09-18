"""Was der Abholer aus einer Vorlagen-Antwort macht (ADR-0018 D6).

Der Unterschied, der hier geprüft wird, ist der zwischen **keine Aussage** und
**keine Vorlagen** — `null` gegen `[]`. Er entscheidet, was passiert, wenn eine
Konsole nach einem Fehler ein halbes Dokument liefert: bei „keine Aussage"
bleibt beim Kunden alles stehen, bei „keine Vorlagen" wird aufgeräumt. Ohne
diese Unterscheidung wäre eines von beiden nicht möglich — entweder liesse sich
eine Vorlage nie zurückziehen, oder eine alte Konsole würde alle löschen.
"""

from __future__ import annotations

import pytest

from magister_api.tenancy.desired_state import (
    DesiredState,
    DesiredStateUnavailableError,
    DesiredTemplate,
    parse_desired_state,
)

BASE: dict[str, object] = {"settings": {}, "rbac": {}}


def _entry(**over: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "key": "enrollment",
        "language": "de",
        "subject": "Eintritt",
        "body_html": "<p>Hallo</p>",
        "may_override": True,
        "version": 3,
    }
    entry.update(over)
    return entry


def _one(**over: object) -> dict[str, object]:
    return dict(BASE, templates=[_entry(**over)])


def _only(state: DesiredState) -> DesiredTemplate:
    """Die eine erwartete Vorlage — mit der Erwartung als Prüfung."""
    rows = state.templates
    assert rows is not None and len(rows) == 1
    return rows[0]


class TestNoStatementIsNotAnEmptyList:
    def test_a_console_without_the_field_says_nothing(self) -> None:
        """Eine Konsole vor ADR-0018 kennt das Feld nicht.

        Sie darf nicht als „alle Vorlagen entfernen" gelesen werden — das wäre
        ein Datenverlust durch ein Upgrade, das noch nicht passiert ist.
        """
        state = parse_desired_state(BASE)
        assert state.templates is None
        assert state.has_templates is False

    def test_an_explicit_empty_list_is_a_statement(self) -> None:
        state = parse_desired_state(dict(BASE, templates=[]))
        assert state.templates == ()
        assert state.has_templates is True

    def test_null_is_read_as_no_statement(self) -> None:
        # `templates: null` und ein fehlendes Feld sind dasselbe: beides ist
        # keine Aussage. Eine Konsole, die `null` schickt, meint nicht
        # „löschen" — sonst hiesse es `[]`.
        assert parse_desired_state(dict(BASE, templates=None)).templates is None


class TestShape:
    def test_a_complete_entry_comes_through(self) -> None:
        row = _only(parse_desired_state(_one()))
        assert (row.key, row.language, row.version, row.may_override) == (
            "enrollment",
            "de",
            3,
            True,
        )

    def test_a_missing_subject_is_allowed(self) -> None:
        assert _only(parse_desired_state(_one(subject=None))).subject is None

    def test_may_override_defaults_to_true(self) -> None:
        """Die Vorgabe ist „überschreibbar", nicht „gesperrt".

        Eine fehlende Angabe darf nicht in eine Sperre kippen: das wäre der
        Fall, in dem ein Feldname-Tippfehler in der Konsole dem Kunden
        stillschweigend seine Vorlage abschaltet.
        """
        entry = _entry()
        del entry["may_override"]
        assert _only(parse_desired_state(dict(BASE, templates=[entry]))).may_override is True

    @pytest.mark.parametrize("bad", ["nicht-eine-liste", 5, {"key": "x"}])
    def test_templates_must_be_a_list(self, bad: object) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(dict(BASE, templates=bad))

    def test_an_entry_without_a_key_is_refused(self) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(dict(BASE, templates=[{"language": "de", "body_html": "x"}]))

    def test_an_entry_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(dict(BASE, templates=["enrollment"]))

    def test_version_zero_is_refused(self) -> None:
        # Eine 0 wäre von „noch nie quittiert" (`NULL`) nicht zu unterscheiden.
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(_one(version=0))

    def test_a_version_that_is_not_a_number_is_refused(self) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(_one(version="drei"))

    def test_two_entries_for_the_same_pair_are_refused(self) -> None:
        """Welche gilt, wäre Zufall der Reihenfolge.

        Also kein Zustand, den man materialisieren darf: die Datenbank hat
        einen Unique-Index, und der eine Eintrag würde den anderen still
        gewinnen lassen.
        """
        both = dict(BASE, templates=[_entry(), _entry(subject="anders")])
        with pytest.raises(DesiredStateUnavailableError) as exc:
            parse_desired_state(both)
        assert "doppelte" in str(exc.value)

    def test_the_rest_of_the_state_still_parses(self) -> None:
        # Die Vorlagen sind ein Zusatz, keine Umstellung: Einstellungen und
        # Rechte müssen unverändert durchkommen.
        state = parse_desired_state(
            {
                "settings": {"ad_sync_interval_minutes": 15},
                "rbac": {"kl": ["user.read"]},
                "templates": [],
            }
        )
        assert state.settings == {"ad_sync_interval_minutes": 15}
        assert state.rbac == {"kl": ["user.read"]}
