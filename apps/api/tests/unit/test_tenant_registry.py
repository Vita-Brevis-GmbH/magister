"""Die Registry ist die Sicherheitsgrenze für Bezeichner (ADR-0013 D1)."""

from __future__ import annotations

import pytest

from magister_api.tenancy.registry import (
    SLUG_PATTERN,
    Tenant,
    TenantConfigError,
    TenantRegistry,
    TenantStatus,
    registry_from_json,
    single_tenant_registry,
)

DSN_A = "postgresql+asyncpg://r_alpha@db/magister"
DSN_B = "postgresql+asyncpg://r_beta@db/magister"


def _tenant(slug: str, **over: object) -> Tenant:
    base: dict[str, object] = {
        "slug": slug,
        "name": slug,
        "dsn": f"postgresql+asyncpg://r_{slug}@db/magister",
        "schema_name": f"t_{slug}",
        "db_role": f"r_{slug}",
        "schema_version": "0044_local_admin_totp",
        "status": TenantStatus.ACTIVE,
        "hostname": f"{slug}.magister.ch",
    }
    base.update(over)
    return Tenant(**base)  # type: ignore[arg-type]


def test_the_slug_pattern_matches_the_console() -> None:
    """Konsole und Datenebene müssen denselben Slug akzeptieren.

    Driftet das auseinander, legt die Konsole Kunden an, die die Datenebene
    beim Start ablehnt — und das fällt erst im Betrieb auf. Die Konsole kann
    ``magister_api`` nicht importieren (getrennte Anwendung, getrennte
    Abhängigkeiten), deshalb ist beiden Seiten dasselbe Literal
    festgeschrieben: ein Test hier, ein Test in
    ``cockpit/api/tests/test_tenants.py``. Eine Änderung auf einer Seite
    bricht einen der beiden.
    """
    assert SLUG_PATTERN.pattern == r"^[a-z][a-z0-9_]{1,30}$"


class TestSingleTenant:
    def test_the_fallback_registry_is_a_normal_registry(self) -> None:
        """n=1 ist kein Sonderweg, sondern eine Zeile (ADR-0013 D8)."""
        reg = single_tenant_registry(dsn="postgresql+asyncpg://magister@db/magister")
        assert reg.is_single_tenant
        assert reg.tenants[0].schema_name == "public"
        assert reg.tenants[0].db_role is None

    def test_it_answers_for_any_hostname(self) -> None:
        # On-prem wählt der Betreiber den Namen; er steht in keiner Registry.
        reg = single_tenant_registry(dsn=DSN_A)
        for host in ("magister.schule.ch", "10.0.0.9:8000", None, "[::1]:8000"):
            assert reg.resolve_host(host) is not None

    def test_an_empty_registry_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="leer"):
            TenantRegistry([])


class TestMultiTenantHardening:
    """Ab zwei Mandanten gibt es etwas zu trennen — dann keine Abkürzungen."""

    def test_a_missing_db_role_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="db_role fehlt"):
            TenantRegistry([_tenant("alpha"), _tenant("beta", db_role=None)])

    def test_a_shared_login_role_is_refused(self) -> None:
        """Der Befund, der die Bauart geändert hat.

        Postgres prüft ``SET ROLE`` gegen den Sitzungsbenutzer. Eine gemeinsame
        Anmelderolle mit Mitgliedschaft in allen Mandantenrollen kann daher aus
        jedem Mandanten in jeden anderen wechseln — ``SET LOCAL ROLE`` allein
        wäre also keine Grenze.
        """
        shared = "postgresql+asyncpg://app_login@db/magister"
        with pytest.raises(TenantConfigError, match="eigene"):
            TenantRegistry([_tenant("alpha", dsn=shared), _tenant("beta", dsn=shared)])

    def test_the_dsn_login_must_equal_the_tenant_role(self) -> None:
        # Eigener Anmeldename, aber nicht der der Mandantenrolle: dann hängt die
        # Trennung wieder an SET LOCAL ROLE statt an der Verbindung.
        odd = "postgresql+asyncpg://r_gamma@db/magister"
        with pytest.raises(TenantConfigError, match="db_role ist aber"):
            TenantRegistry([_tenant("alpha"), _tenant("beta", dsn=odd)])

    def test_a_catch_all_host_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="hostname fehlt"):
            TenantRegistry([_tenant("alpha"), _tenant("beta", hostname=None)])

    def test_public_schema_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="public"):
            TenantRegistry([_tenant("alpha"), _tenant("beta", schema_name="public")])

    def test_duplicate_hostnames_are_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="doppelt"):
            TenantRegistry([_tenant("alpha"), _tenant("beta", hostname="alpha.magister.ch")])

    def test_two_tenants_may_share_a_schema_name_in_different_clusters(self) -> None:
        # „Eigene Datenbank" ist derselbe Code-Pfad; dort darf das Schema
        # denselben Namen haben.
        reg = TenantRegistry(
            [
                _tenant("alpha", schema_name="t_default"),
                _tenant(
                    "beta",
                    schema_name="t_default",
                    dsn="postgresql+asyncpg://r_beta@db2/magister",
                ),
            ]
        )
        assert len(reg.tenants) == 2


class TestIdentifierValidation:
    """Schema- und Rollenname gehen unquotiert in ein SET — daher streng."""

    @pytest.mark.parametrize(
        "slug",
        [
            "Alpha",  # Grossbuchstabe
            "a",  # zu kurz
            "1alpha",  # beginnt mit Ziffer
            "alpha-beta",  # Bindestrich
            'a"; DROP SCHEMA t_beta; --',
            "a" * 32,  # zu lang
            "",
        ],
    )
    def test_a_bad_slug_is_refused(self, slug: str) -> None:
        payload = f'[{{"slug": {slug!r}, "hostname": "x.test"}}]'
        with pytest.raises(TenantConfigError):
            registry_from_json(payload, default_dsn=DSN_A)

    def test_a_system_schema_is_refused(self) -> None:
        payload = '[{"slug": "alpha", "schema_name": "pg_catalog"}]'
        with pytest.raises(TenantConfigError, match="Systemschema"):
            registry_from_json(payload, default_dsn=DSN_A)

    def test_an_injected_schema_name_is_refused(self) -> None:
        payload = '[{"slug": "alpha", "schema_name": "t_alpha, t_beta"}]'
        with pytest.raises(TenantConfigError, match="Bezeichner"):
            registry_from_json(payload, default_dsn=DSN_A)


class TestHostResolution:
    def test_an_exact_match_beats_the_catch_all(self) -> None:
        """Sonst schluckt in einer On-prem-Installation der erste alles."""
        reg = TenantRegistry([_tenant("alpha", db_role=None, hostname=None, dsn=DSN_A)])
        assert reg.resolve_host("irgendwas.test") is not None

        reg2 = TenantRegistry([_tenant("alpha"), _tenant("beta")])
        assert reg2.resolve_host("beta.magister.ch") is not None
        hit = reg2.resolve_host("beta.magister.ch")
        assert hit is not None and hit.slug == "beta"

    @pytest.mark.parametrize(
        "host",
        ["alpha.magister.ch", "ALPHA.Magister.CH", "alpha.magister.ch:443", " alpha.magister.ch "],
    )
    def test_hostnames_are_normalized(self, host: str) -> None:
        reg = TenantRegistry([_tenant("alpha"), _tenant("beta")])
        hit = reg.resolve_host(host)
        assert hit is not None and hit.slug == "alpha"

    def test_an_unknown_host_resolves_to_nothing(self) -> None:
        reg = TenantRegistry([_tenant("alpha"), _tenant("beta")])
        assert reg.resolve_host("gamma.magister.ch") is None
        assert reg.resolve_host(None) is None

    def test_a_forged_host_list_does_not_pick_the_second_entry(self) -> None:
        """ "beta.magister.ch, alpha.magister.ch" darf nicht beta ergeben."""
        reg = TenantRegistry([_tenant("alpha"), _tenant("beta")])
        hit = reg.resolve_host("gamma.magister.ch, alpha.magister.ch")
        assert hit is None


class TestJsonLoading:
    def test_a_full_entry_round_trips(self) -> None:
        reg = registry_from_json(
            '[{"slug": "musterstadt", "name": "Gemeinde Musterstadt", '
            '"hostname": "musterstadt.magister.ch", '
            f'"dsn": "{DSN_A}", "db_role": "r_alpha", '
            '"schema_name": "t_musterstadt", "schema_version": "0044_local_admin_totp"}]',
            default_dsn=DSN_B,
        )
        t = reg.tenants[0]
        assert (t.slug, t.schema_name, t.db_role) == ("musterstadt", "t_musterstadt", "r_alpha")
        assert t.expected_session_user == "r_alpha"

    def test_schema_and_role_default_from_the_slug(self) -> None:
        reg = registry_from_json('[{"slug": "alpha"}]', default_dsn=DSN_A)
        assert reg.tenants[0].schema_name == "t_alpha"

    def test_broken_json_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="JSON"):
            registry_from_json("{nicht json", default_dsn=DSN_A)

    def test_a_non_list_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="Liste"):
            registry_from_json('{"slug": "alpha"}', default_dsn=DSN_A)

    def test_an_unknown_status_is_refused(self) -> None:
        with pytest.raises(TenantConfigError, match="status"):
            registry_from_json('[{"slug": "alpha", "status": "halb-aktiv"}]', default_dsn=DSN_A)


class TestStatus:
    @pytest.mark.parametrize(
        ("status", "served"),
        [
            (TenantStatus.ACTIVE, True),
            (TenantStatus.PROVISIONING, False),
            (TenantStatus.SUSPENDED, False),
            (TenantStatus.OFFBOARDING, False),
        ],
    )
    def test_only_an_active_tenant_is_served(self, status: TenantStatus, served: bool) -> None:
        # provisioning und offboarding sind Übergänge, in denen Daten wandern;
        # eine Anfrage dorthin liest einen halben Zustand.
        assert status.serves_requests is served
