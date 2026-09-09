"""Die Grenzen, die der Agent selbst zieht (ADR-0014).

Die Annahme hinter jedem Test hier: **die Plattform könnte kompromittiert
sein.** Der Agent hat ein Dienstkonto, das Passwörter setzen und Gruppen ändern
darf; wer die Plattform übernimmt, würde genau das ausnutzen. Diese Grenzen
sind lokal konfiguriert — die Plattform kann sie nicht ändern, nicht lesen und
nicht abschalten.
"""

from __future__ import annotations

import pytest

from connector_agent.guardrails import (
    ALLOWED_METHODS,
    DEFAULT_PROTECTED_GROUPS,
    Guardrails,
    GuardrailViolationError,
    dn_is_within,
    normalize_dn,
)

SCHULE = "OU=Schule,OU=Magister,DC=gemeinde,DC=local"
LEHRER = f"CN=Muster Hans,OU=Lehrer,{SCHULE}"


def _rails(**over: object) -> Guardrails:
    base: dict[str, object] = {"allowed_ous": frozenset({SCHULE})}
    base.update(over)
    return Guardrails(**base)  # type: ignore[arg-type]


class TestDnComparison:
    def test_case_and_spacing_do_not_matter(self) -> None:
        # LDAP-DNs sind gross-/kleinschreibungsunabhängig und dürfen
        # Leerzeichen um die Kommas haben. Ein naiver endswith-Vergleich
        # würde das übersehen — und damit die Allowlist umgehbar machen.
        assert normalize_dn("CN=A, OU=X , DC=y") == "cn=a,ou=x,dc=y"
        assert dn_is_within("cn=a, ou=lehrer , " + SCHULE.lower(), frozenset({SCHULE}))

    def test_a_sibling_ou_with_a_shared_prefix_is_outside(self) -> None:
        """``OU=SchuleAB`` darf nicht als „innerhalb von ``OU=Schule``" gelten.

        Der Vergleich läuft über RDN-Grenzen, nicht über Zeichenketten. Ohne
        das wäre die Allowlist mit einem passend benannten OU umgehbar.
        """
        nachbar = "CN=X,OU=SchuleAB,OU=Magister,DC=gemeinde,DC=local"
        assert not dn_is_within(nachbar, frozenset({SCHULE}))

    def test_the_base_itself_counts_as_inside(self) -> None:
        assert dn_is_within(SCHULE, frozenset({SCHULE}))

    def test_an_empty_allowlist_matches_nothing(self) -> None:
        assert not dn_is_within(LEHRER, frozenset())


class TestMethodAllowlist:
    def test_the_allowlist_matches_the_platform(self) -> None:
        """Agent und Plattform müssen dieselbe Methodenmenge kennen.

        Der Agent ist ein eigenständiges Paket und kann ``magister_api`` zur
        Prüfzeit nicht voraussetzen, deshalb wird die Quelle gelesen. Driftet
        eine Seite, nimmt die Plattform Aufträge an, die der Agent ablehnt.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2] / "apps" / "api" / "magister_api" / "ad" / "rpc.py"
        )
        text = source.read_text(encoding="utf-8")
        block = text.split("ALLOWED_METHODS: frozenset[str] = frozenset(", 1)[1].split(")", 1)[0]
        platform = {line.strip().strip('",') for line in block.splitlines() if '"' in line}
        assert platform == set(ALLOWED_METHODS)

    @pytest.mark.parametrize(
        "method", ["ldap_search", "run_powershell", "authenticate", "", "__class__"]
    )
    def test_anything_else_is_refused(self, method: str) -> None:
        with pytest.raises(GuardrailViolationError, match="Allowlist"):
            _rails().check(method, {})

    def test_a_dunder_cannot_sneak_through_as_a_method(self) -> None:
        # Der Methodenname landet in einem getattr. Ohne die Allowlist wäre
        # das ein Weg, beliebige Attribute des Clients anzusprechen.
        with pytest.raises(GuardrailViolationError):
            _rails().check("__init__", {})


class TestOuAllowlist:
    def test_a_dn_inside_is_allowed(self) -> None:
        _rails().check("modify_password", {"user_dn": LEHRER, "new_password": "x"})

    def test_a_dn_outside_is_refused(self) -> None:
        fremd = "CN=Admin,CN=Users,DC=gemeinde,DC=local"
        with pytest.raises(GuardrailViolationError, match="ausserhalb"):
            _rails().check("modify_password", {"user_dn": fremd, "new_password": "x"})

    def test_a_domain_controller_ou_is_refused(self) -> None:
        """Der Angriff, um den es geht.

        Wer die Plattform übernimmt, würde versuchen, ein Konto in eine
        privilegierte OU zu legen oder eines dort anzufassen.
        """
        dc = "CN=DC01,OU=Domain Controllers,DC=gemeinde,DC=local"
        with pytest.raises(GuardrailViolationError):
            _rails().check("set_account_enabled", {"user_dn": dc, "enabled": True})

    def test_the_create_target_ou_is_checked_too(self) -> None:
        with pytest.raises(GuardrailViolationError, match="ou_dn"):
            _rails().check(
                "create_user",
                {"ou_dn": "OU=Fremd,DC=gemeinde,DC=local", "common_name": "X"},
            )

    def test_an_empty_allowlist_refuses_directory_work(self) -> None:
        """Leer heisst NICHT „alles erlaubt".

        Eine Grenze, die sich durch Weglassen der Konfiguration abschalten
        lässt, ist keine Grenze — und ein leeres Feld ist der
        wahrscheinlichste Konfigurationsfehler.
        """
        with pytest.raises(GuardrailViolationError, match="keine OU-Allowlist"):
            Guardrails().check("modify_password", {"user_dn": LEHRER})

    def test_an_empty_allowlist_still_allows_a_connection_probe(self) -> None:
        # Sonst könnte man nicht prüfen, ob der Agent überhaupt ans AD kommt.
        Guardrails().check("probe_service_connection", {})


class TestProtectedGroups:
    def test_domain_admins_is_refused(self) -> None:
        with pytest.raises(GuardrailViolationError, match="Denylist"):
            _rails(allowed_ous=frozenset({"DC=gemeinde,DC=local"})).check(
                "add_user_to_groups",
                {
                    "user_dn": "CN=X,DC=gemeinde,DC=local",
                    "group_dns": ["CN=Domain Admins,CN=Users,DC=gemeinde,DC=local"],
                },
            )

    def test_the_german_name_is_refused_too(self) -> None:
        """Ein deutschsprachiges AD heisst ``Domänen-Admins``.

        Eine Denylist, die nur englisch kann, ist bei einem Schweizer Kunden
        wertlos — und genau dort läuft dieses Produkt.
        """
        with pytest.raises(GuardrailViolationError, match="Denylist"):
            _rails(allowed_ous=frozenset({"DC=gemeinde,DC=local"})).check(
                "add_user_to_groups",
                {
                    "user_dn": "CN=X,DC=gemeinde,DC=local",
                    "group_dns": ["CN=Domänen-Admins,CN=Users,DC=gemeinde,DC=local"],
                },
            )

    def test_removal_from_a_protected_group_is_refused_as_well(self) -> None:
        # Auch das Entfernen: einen Administrator aus seiner Gruppe zu werfen
        # ist ein Denial-of-Service auf das Kundennetz.
        with pytest.raises(GuardrailViolationError, match="Denylist"):
            _rails(allowed_ous=frozenset({"DC=gemeinde,DC=local"})).check(
                "remove_user_from_groups",
                {
                    "user_dn": "CN=X,DC=gemeinde,DC=local",
                    "group_dns": ["CN=Administratoren,CN=Builtin,DC=gemeinde,DC=local"],
                },
            )

    def test_an_ordinary_group_inside_the_allowlist_passes(self) -> None:
        _rails().check(
            "add_user_to_groups",
            {"user_dn": LEHRER, "group_dns": [f"CN=Lehrer-Alle,OU=Gruppen,{SCHULE}"]},
        )

    def test_the_default_list_covers_the_usual_suspects(self) -> None:
        for name in ("domain admins", "domänen-admins", "enterprise admins", "administratoren"):
            assert name in DEFAULT_PROTECTED_GROUPS


class TestProtectedAttributes:
    @pytest.mark.parametrize(
        "attribute",
        ["memberOf", "primaryGroupID", "userAccountControl", "servicePrincipalName", "adminCount"],
    )
    def test_a_privilege_attribute_is_refused(self, attribute: str) -> None:
        """Wege, ein Konto zu privilegieren oder eine Identität zu übernehmen.

        ``userAccountControl`` schaltet Konten frei und Kerberos-Delegation
        ein, ``servicePrincipalName`` erlaubt Kerberoasting, ``memberOf`` ist
        berechnet. Nichts davon setzt der Agent, auch nicht auf Befehl.
        """
        with pytest.raises(GuardrailViolationError, match="privilegieren"):
            _rails().check(
                "modify_user_attributes",
                {"user_dn": LEHRER, "attributes": {attribute: "1"}},
            )

    def test_an_ordinary_attribute_passes(self) -> None:
        _rails().check(
            "modify_user_attributes",
            {"user_dn": LEHRER, "attributes": {"telephoneNumber": "031 000 00 00"}},
        )
