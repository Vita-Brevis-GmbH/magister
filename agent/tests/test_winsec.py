"""Rechteprüfung unter Windows über die DACL (ADR-0014).

Warum diese Datei existiert: der POSIX-Weg ist unter Windows **nicht bloss
ungenau, er ist unbrauchbar**. ``os.stat()`` liefert dort erfundene
Modus-Bits — Verzeichnisse melden ``0o777`` —, also hätte
``assert_permissions`` den Dienst bei jedem Start abgelehnt, egal wie gut die
Rechte gesetzt sind. Und die Prüfung stumm zu überspringen wäre schlimmer:
dann liefe der Agent, und die Zusage über seinen privaten Schlüssel wäre
unbelegt.

Die Zerlegung der SDDL ist deshalb Textarbeit und hier vollständig geprüft.
Nur das Lesen der ACL braucht Windows; die SDDL-Strings unten sind echte
Ausgaben von ``ConvertSecurityDescriptorToStringSecurityDescriptorW``.
"""

from __future__ import annotations

import pytest

from connector_agent.winsec import (
    ALLOWED_TRUSTEES,
    granting_trustees,
    inherits_from_parent,
    offending_trustees,
)

#: So sieht es aus, wenn das Installationsprogramm seine Arbeit getan hat:
#: Vererbung abgeschaltet (``P``), Vollzugriff nur für SYSTEM und
#: Administratoren, vererbt an Dateien und Unterverzeichnisse (``OICI``).
GOOD = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

#: Der Normalzustand eines frisch angelegten Verzeichnisses unter
#: ``%ProgramData%``: „Benutzer" dürfen lesen. Auf einem Mitgliedsserver ist
#: das jeder angemeldete Domänenbenutzer.
INHERITED_PROGRAMDATA = (
    "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;0x1200a9;;;BU)"
    "(A;CIID;LC;;;BU)(A;CIID;DC;;;BU)"
)


class TestGrantingTrustees:
    def test_a_locked_down_acl_grants_only_system_and_admins(self) -> None:
        assert granting_trustees(GOOD) == ["SY", "BA"]
        assert offending_trustees(GOOD) == []

    def test_deny_aces_are_not_grants(self) -> None:
        """Ein Verweigern-Eintrag für „Jeder" ist kein Fund, sondern gut."""
        sddl = "D:P(D;OICI;FA;;;WD)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        assert granting_trustees(sddl) == ["SY", "BA"]
        assert offending_trustees(sddl) == []

    def test_audit_aces_are_not_grants(self) -> None:
        """``S:``-Einträge sehen wie ACEs aus, gewähren aber nichts.

        Sie mitzuzählen ergäbe eine Falschmeldung — und eine Falschmeldung in
        dieser Prüfung heisst: der Dienst startet nicht.
        """
        sddl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)S:AI(AU;SAFA;FA;;;WD)"
        assert granting_trustees(sddl) == ["SY", "BA"]
        assert offending_trustees(sddl) == []

    def test_every_allowed_trustee_is_accepted(self) -> None:
        for trustee in sorted(ALLOWED_TRUSTEES):
            sddl = f"D:P(A;OICI;FA;;;{trustee})"
            assert offending_trustees(sddl) == [], trustee

    def test_raw_sids_are_recognised_like_the_short_forms(self) -> None:
        """SDDL schreibt bekannte Treuhänder mal als Kurzform, mal als SID."""
        assert offending_trustees("D:P(A;OICI;FA;;;S-1-5-18)(A;OICI;FA;;;S-1-5-32-544)") == []


class TestOffendingTrustees:
    def test_the_default_programdata_acl_is_a_finding(self) -> None:
        """Genau der Zustand, den ein `mkdir` ohne ACL-Arbeit hinterlässt."""
        problems = offending_trustees(INHERITED_PROGRAMDATA)
        assert problems, "die Standard-ACL von ProgramData muss auffallen"
        assert any("Benutzer" in item for item in problems)

    @pytest.mark.parametrize(
        ("trustee", "expected"),
        [
            ("WD", "Jeder"),
            ("BU", "Benutzer"),
            ("AU", "Authentifizierte Benutzer"),
            ("AN", "Anonyme"),
        ],
    )
    def test_a_finding_says_who_in_plain_words(self, trustee: str, expected: str) -> None:
        """Ohne Klartext steht in der Meldung ``WD``, und niemand weiss, was fehlt."""
        problems = offending_trustees(f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{trustee})")
        assert len(problems) == 1
        assert expected in problems[0]
        # Die Kurzform bleibt dabei stehen — danach sucht man in icacls.
        assert trustee in problems[0]

    def test_an_unknown_trustee_is_reported_verbatim(self) -> None:
        """Eine Domänengruppe hat keine Kurzform. Gemeldet wird sie trotzdem."""
        sid = "S-1-5-21-1234567890-1234567890-1234567890-1108"
        problems = offending_trustees(f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})")
        assert problems == [sid]

    def test_a_duplicated_trustee_is_named_once(self) -> None:
        """Eine ACL trägt denselben Treuhänder gern zweimal (geerbt und direkt)."""
        sddl = "D:P(A;OICI;FA;;;BU)(A;;LC;;;BU)(A;OICI;FA;;;SY)"
        assert len(offending_trustees(sddl)) == 1


class TestInheritance:
    def test_a_protected_acl_does_not_inherit(self) -> None:
        assert not inherits_from_parent(GOOD)

    def test_an_inheriting_acl_is_flagged(self) -> None:
        """Sonst kann das übergeordnete Verzeichnis später Rechte hinzufügen.

        Dann stimmt die Prüfung heute und morgen nicht mehr — und niemand
        merkt es, weil beim Agenten nichts geändert wurde.
        """
        assert inherits_from_parent(INHERITED_PROGRAMDATA)

    def test_a_sddl_without_a_dacl_is_treated_as_inheriting(self) -> None:
        """Kein ``D:``-Abschnitt heisst: keine Aussage. Also die strengere annehmen."""
        assert inherits_from_parent("O:BAG:BA")
        assert granting_trustees("O:BAG:BA") == []


class TestMalformedInput:
    """Die ACL kommt aus der Windows-API; kaputt darf sie trotzdem nicht knallen."""

    @pytest.mark.parametrize(
        "sddl",
        [
            "",
            "D:",
            "D:P",
            "D:P()",
            "D:P(A;OICI;FA)",  # zu wenige Felder
            "kein sddl",
        ],
    )
    def test_it_does_not_raise(self, sddl: str) -> None:
        assert granting_trustees(sddl) == []
        assert offending_trustees(sddl) == []


class TestProtectedGroupsAreAFloor:
    """Die eingebaute Liste ist eine Untergrenze, keine Vorgabe (ADR-0014).

    Steht hier bei den Rechte-Tests, weil es dieselbe Art von Zusage ist: eine,
    die die Plattform nicht aufheben kann und der Kunde nicht versehentlich.

    Der Fehler, den das verhindert, wäre still gewesen: wer eine eigene
    geschützte Gruppe einträgt, hätte damit den Schutz für „Domänen-Admins"
    verloren. Alles läuft weiter, und die Plattform darf plötzlich Konten in
    die Domänen-Admins aufnehmen.
    """

    def test_configured_groups_are_added_not_substituted(self) -> None:
        from connector_agent.config import AgentConfig
        from connector_agent.guardrails import DEFAULT_PROTECTED_GROUPS

        config = AgentConfig.from_mapping(
            {"endpoint": "https://connect.example.ch:46200", "protected_groups": ["Schulleitung"]}
        )
        assert "schulleitung" in config.protected_groups
        assert DEFAULT_PROTECTED_GROUPS <= config.protected_groups

    def test_domain_admins_stay_protected_whatever_is_configured(self) -> None:
        from connector_agent.config import AgentConfig

        config = AgentConfig.from_mapping(
            {"endpoint": "https://connect.example.ch:46200", "protected_groups": ["irgendwas"]}
        )
        # Deutsch und englisch, weil beide Schreibweisen in Kundendomänen
        # vorkommen und die Plattform nicht weiss, welche gilt.
        assert "domänen-admins" in config.protected_groups
        assert "domain admins" in config.protected_groups

    def test_an_empty_list_leaves_the_builtin_list_in_force(self) -> None:
        from connector_agent.config import AgentConfig
        from connector_agent.guardrails import DEFAULT_PROTECTED_GROUPS

        config = AgentConfig.from_mapping(
            {"endpoint": "https://connect.example.ch:46200", "protected_groups": []}
        )
        assert config.protected_groups == DEFAULT_PROTECTED_GROUPS
