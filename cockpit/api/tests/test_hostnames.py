"""Hostname eines Kunden: Form, Domäne, reservierte Namen (Abnahme-Testplan K-11a)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cockpit_api.schemas.tenant import TenantCreate
from cockpit_api.services.hostnames import HostnameError, check_placement, check_syntax

DOMAIN = "dev-mgmt.int.vitabrevis.ch"
PLATFORM = (f"konsole.{DOMAIN}", f"connect.{DOMAIN}")


class TestSyntax:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Thun.Dev-Mgmt.Int.Vitabrevis.CH", "thun.dev-mgmt.int.vitabrevis.ch"),
            ("  bern.magister.ch.  ", "bern.magister.ch"),
            ("schule-1.magister.ch", "schule-1.magister.ch"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert check_syntax(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "thun_west.magister.ch",  # Unterstrich: kein Hostname, kein Zertifikat
            "-thun.magister.ch",
            "thun-.magister.ch",
            "thun..magister.ch",
            "thün.magister.ch",
            "thun",
            "172.25.12.10",
            "::1",
            f"{'a' * 64}.magister.ch",
        ],
    )
    def test_rejects(self, raw: str) -> None:
        with pytest.raises(HostnameError):
            check_syntax(raw)

    def test_the_schema_uses_it(self) -> None:
        with pytest.raises(ValidationError) as err:
            TenantCreate(slug="thun", name="Thun", hostname="thun_west.magister.ch")
        assert "Unterstrich" in str(err.value)


class TestPlacement:
    def test_a_customer_one_level_below_the_domain_is_fine(self) -> None:
        check_placement(f"thun.{DOMAIN}", tenant_domain=DOMAIN, platform_hosts=PLATFORM)

    @pytest.mark.parametrize("host", list(PLATFORM))
    def test_the_platform_names_are_taken(self, host: str) -> None:
        with pytest.raises(HostnameError, match="Plattform"):
            check_placement(host, tenant_domain=DOMAIN, platform_hosts=PLATFORM)

    @pytest.mark.parametrize("first", ["konsole", "console", "connect"])
    def test_reserved_labels_even_without_configured_names(self, first: str) -> None:
        with pytest.raises(HostnameError, match="reserviert"):
            check_placement(f"{first}.{DOMAIN}", tenant_domain="", platform_hosts=())

    def test_outside_the_domain(self) -> None:
        with pytest.raises(HostnameError, match="unter"):
            check_placement("thun.example.com", tenant_domain=DOMAIN, platform_hosts=PLATFORM)

    def test_a_lookalike_domain_is_outside(self) -> None:
        with pytest.raises(HostnameError):
            check_placement(f"thun.evil-{DOMAIN}", tenant_domain=DOMAIN, platform_hosts=PLATFORM)

    def test_two_levels_below_is_not_covered_by_the_wildcard(self) -> None:
        with pytest.raises(HostnameError, match="eine Ebene"):
            check_placement(f"a.thun.{DOMAIN}", tenant_domain=DOMAIN, platform_hosts=PLATFORM)

    def test_the_domain_itself_is_no_customer(self) -> None:
        with pytest.raises(HostnameError):
            check_placement(DOMAIN, tenant_domain=DOMAIN, platform_hosts=PLATFORM)

    def test_without_a_domain_only_form_and_reserved_names_count(self) -> None:
        check_placement("schule.example.org", tenant_domain="", platform_hosts=PLATFORM)
