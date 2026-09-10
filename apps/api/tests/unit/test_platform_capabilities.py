"""Plattform-Capabilities kann keine Kundenrolle halten (ADR-0017 D5).

Der Fund, um den es hier geht: `effective_capabilities` gab einem Admin
bisher `frozenset(Capability)` zurück — **alles, was in der Aufzählung
steht**. Wären die Plattform-Rechte einfach dazugekommen, hätte jeder
Kunden-Admin sie damit geschenkt bekommen, und D5 wäre eine Absicht ohne
Wirkung gewesen.

Der Super-Role heisst deshalb ab jetzt „alles, was ein Kunde haben kann" und
nicht mehr „alles". Diese Datei ist die Prüfung, die das festhält — für die
nächste Person, die eine Capability hinzufügt.
"""

from __future__ import annotations

import pytest

from magister_api.auth.capabilities import (
    PLATFORM_CAPABILITIES,
    TENANT_CAPABILITIES,
    Capability,
    RbacMatrix,
    effective_capabilities,
    has_capability,
)
from magister_api.auth.current_user import AuthenticatedUser


def _user(*roles: str, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        ad_object_guid="00000000-0000-0000-0000-000000000001",
        upn="test@example.ch",
        is_admin=is_admin,
        school_scope=(),
        roles=tuple(roles),
        expires_at=None,
    )


EMPTY_MATRIX = RbacMatrix(role_caps={}, admin_roles=frozenset({"admin"}))


class TestTheSplitIsComplete:
    def test_the_two_sets_do_not_overlap(self) -> None:
        assert not (PLATFORM_CAPABILITIES & TENANT_CAPABILITIES)

    def test_together_they_are_the_whole_enum(self) -> None:
        """Eine neue Capability muss auf einer der zwei Seiten landen.

        Ohne diese Prüfung könnte eine dritte Kategorie entstehen — und die
        Frage „darf ein Kunden-Admin das?" hätte keine Antwort.
        """
        assert (PLATFORM_CAPABILITIES | TENANT_CAPABILITIES) == frozenset(Capability)

    def test_every_platform_capability_is_named_as_such(self) -> None:
        for cap in PLATFORM_CAPABILITIES:
            assert cap.value.startswith("platform."), (
                f"{cap.value} steht in PLATFORM_CAPABILITIES, heisst aber nicht so. "
                "Der Name ist die Dokumentation an der Stelle, an der jemand die "
                "Matrix liest."
            )

    def test_no_tenant_capability_pretends_to_be_a_platform_one(self) -> None:
        for cap in TENANT_CAPABILITIES:
            assert not cap.value.startswith("platform.")


class TestTheCustomerAdminDoesNotHoldThem:
    def test_admin_holds_every_tenant_capability(self) -> None:
        held = effective_capabilities(_user("admin", is_admin=True), EMPTY_MATRIX)
        assert held == TENANT_CAPABILITIES

    def test_admin_holds_no_platform_capability(self) -> None:
        """Die eigentliche Aussage von D5."""
        held = effective_capabilities(_user("admin", is_admin=True), EMPTY_MATRIX)
        assert not (held & PLATFORM_CAPABILITIES)

    @pytest.mark.parametrize("cap", sorted(PLATFORM_CAPABILITIES, key=lambda c: c.value))
    def test_has_capability_says_no_to_an_admin(self, cap: Capability) -> None:
        # Über `has_capability`, weil der frühere Kurzschluss dort sass:
        # `if user.is_admin: return True` hätte jedes Plattform-Recht gewährt,
        # ohne `effective_capabilities` überhaupt zu fragen.
        assert not has_capability(_user("admin", is_admin=True), EMPTY_MATRIX, cap)

    def test_admin_still_passes_a_tenant_capability(self) -> None:
        assert has_capability(
            _user("admin", is_admin=True), EMPTY_MATRIX, Capability.USER_ADMINISTER
        )

    def test_a_matrix_row_does_not_grant_a_platform_capability(self) -> None:
        """Der Gürtel zum Hosenträger.

        Der RBAC-Dienst verhindert das Schreiben einer solchen Zeile. Falls
        sie trotzdem existiert — von Hand eingefügt, aus einer alten Sicherung
        eingespielt —, soll sie nicht wirken.
        """
        matrix = RbacMatrix(
            role_caps={"schulleitung": frozenset({Capability.PLATFORM_SETTINGS_MANAGE})},
            admin_roles=frozenset({"admin"}),
        )
        user = _user("schulleitung")
        assert effective_capabilities(user, matrix) == frozenset()
        assert not has_capability(user, matrix, Capability.PLATFORM_SETTINGS_MANAGE)
