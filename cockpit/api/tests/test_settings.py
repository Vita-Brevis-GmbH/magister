"""Systemeinstellungen und Rechte-Matrix als Soll-Zustand (ADR-0017).

Was hier geprüft wird, ist vor allem **was nicht hineinkommt**. Die Konsole
besitzt die Politik und nicht die Geheimnisse (D2); ein Feld, das ein
Geheimnis trägt, muss beim ersten Schreibversuch auffallen — nicht beim ersten
Vorfall.

Dazu die zwei Unterscheidungen, die sonst niemandem auffallen, bis sie
wehtun: `null` heisst „auf die Vorgabe zurück" und nicht „auf null setzen",
und eine leere Rechte-Matrix ist etwas anderes als keine.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.services.settings import (
    POLICY_KEYS,
    SECRET_LOOKING,
    SECRET_LOOKING_EXEMPT,
    SettingsError,
    effective,
    validate_policy,
    validate_rbac,
)


# --- Reine Logik: die Allowlist selbst -------------------------------------
class TestAllowlistIsTheAuthority:
    """Die Prüfung über die Liste, nicht über die Daten.

    Der Namensfilter zur Laufzeit war der erste Entwurf und war falsch:
    `password_store_enabled` ist ein Schalter, `ad_tls_ca_pem` ein öffentliches
    Zertifikat. Also entscheidet die Liste — und dieser Test bewacht die Liste.
    """

    def test_no_allowlisted_key_looks_like_a_secret(self) -> None:
        offenders = [
            key
            for key in POLICY_KEYS
            if SECRET_LOOKING.search(key) and key not in SECRET_LOOKING_EXEMPT
        ]
        assert offenders == [], (
            f"Diese Politik-Schlüssel sehen aus wie Geheimnisse: {offenders}. "
            "Entweder sie gehören nicht in die Konsole (ADR-0017 D2), oder sie "
            "brauchen einen Eintrag in SECRET_LOOKING_EXEMPT mit der Begründung, "
            "warum sie keines sind."
        )

    def test_every_exemption_carries_a_reason(self) -> None:
        for key, reason in SECRET_LOOKING_EXEMPT.items():
            assert key in POLICY_KEYS, f"{key} ist ausgenommen, steht aber nicht in der Liste."
            assert len(reason) > 20, f"Die Begründung für {key} ist keine."

    def test_the_four_real_secrets_are_not_allowed(self) -> None:
        # Namentlich, damit ein späteres Hinzufügen hier auffällt und nicht
        # nur am Namensmuster hängt.
        for secret in (
            "oidc_client_secret",
            "ad_bind_password",
            "ninja_client_secret",
            "web_tls_key_pem",
        ):
            assert secret not in POLICY_KEYS
            with pytest.raises(SettingsError, match="kein Politik-Schlüssel"):
                validate_policy({secret: "geheim"})

    def test_the_public_certificate_is_allowed(self) -> None:
        # Die drei Zeichen Unterschied, an denen ein Namensfilter scheitert.
        validate_policy({"ad_tls_ca_pem": "-----BEGIN CERTIFICATE-----"})
        validate_policy({"web_tls_cert_pem": "-----BEGIN CERTIFICATE-----"})
        with pytest.raises(SettingsError):
            validate_policy({"web_tls_key_pem": "-----BEGIN PRIVATE KEY-----"})


class TestValidation:
    def test_unknown_key_is_named_in_the_message(self) -> None:
        with pytest.raises(SettingsError, match="ad_dcx"):
            validate_policy({"ad_dcx": ["dc1"]})

    def test_wrong_type_is_named(self) -> None:
        with pytest.raises(SettingsError, match="ad_sync_interval_minutes"):
            validate_policy({"ad_sync_interval_minutes": "sechzig"})

    def test_bool_is_not_an_int(self) -> None:
        # `bool` ist in Python eine Unterklasse von `int`; ohne eine eigene
        # Prüfung ginge `true` als Intervall durch und der Sync liefe jede
        # Minute.
        with pytest.raises(SettingsError, match="Wahrheitswert"):
            validate_policy({"ad_sync_interval_minutes": True})

    def test_none_is_allowed_as_a_reset(self) -> None:
        assert validate_policy({"ad_bind_dn": None}) == {"ad_bind_dn": None}

    def test_rbac_shape(self) -> None:
        assert validate_rbac({"kl": ["user.read"]}) == {"kl": ["user.read"]}
        assert validate_rbac(None) is None
        with pytest.raises(SettingsError):
            validate_rbac({"kl": "user.read"})
        with pytest.raises(SettingsError):
            validate_rbac({"": ["user.read"]})


class TestEffective:
    def test_override_wins_field_by_field(self) -> None:
        merged = effective(
            {"ad_sync_interval_minutes": 60, "instance_profile": "school"},
            {"ad_sync_interval_minutes": 15},
        )
        assert merged == {"ad_sync_interval_minutes": 15, "instance_profile": "school"}

    def test_none_falls_back_to_the_default(self) -> None:
        # Der Unterschied, ohne den es keinen Weg zurück zur Vorgabe gäbe.
        merged = effective({"ad_sync_interval_minutes": 60}, {"ad_sync_interval_minutes": None})
        assert merged == {"ad_sync_interval_minutes": 60}

    def test_defaults_are_not_mutated(self) -> None:
        defaults = {"instance_profile": "school"}
        effective(defaults, {"instance_profile": "municipality"})
        assert defaults == {"instance_profile": "school"}


# --- Über die HTTP-Fläche, mit Datenbank ----------------------------------
SLUG = "settingstest"


@pytest.fixture
def tenant_row(cockpit_schema: str, cockpit_database_url: str) -> str:
    """Ein Kunde in der Konsolen-Datenbank, ohne Bereitstellung.

    Reicht für diese Tests: geprüft werden die Einstellungen, nicht das
    Anlegen. Direkt geschrieben statt über den Endpunkt, weil die
    Bereitstellung einen zweiten Cluster braucht.
    """
    import asyncio

    tenant_id = str(uuid.uuid4())

    async def insert() -> None:
        # Die DSN der Fixture, NICHT settings.database_url: die zeigt auf die
        # Vorgabe, und dieser Test lief dann gegen eine andere Datenbank als
        # die Anwendung. Dreimal passiert.
        engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                        "isolation_mode, dsn_ref, schema_name, db_role, created_at, updated_at) "
                        "VALUES (:id, :slug, :name, :host, 'active', 'school', 'schema', "
                        ":ref, :schema, :role, now(), now())"
                    ),
                    {
                        "id": tenant_id,
                        "slug": SLUG,
                        "name": "Einstellungstest",
                        "host": f"{SLUG}.example.ch",
                        "ref": f"tenant_{SLUG}",
                        "schema": f"t_{SLUG}",
                        "role": f"r_{SLUG}",
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    return tenant_id


def _put(client: TestClient, url: str, body: dict[str, Any]) -> Any:
    return client.put(url, json=body)


class TestPlatformDefaults:
    def test_get_creates_the_singleton(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        response = console_client.get("/api/platform/settings")
        assert response.status_code == 200
        assert response.json()["defaults"] == {}

    def test_put_and_read_back(self, console_client: TestClient, cockpit_schema: str) -> None:
        response = _put(
            console_client,
            "/api/platform/settings",
            {"defaults": {"ad_sync_interval_minutes": 60}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["defaults"] == {"ad_sync_interval_minutes": 60}
        # `bootstrap-token` und nicht „ops@vitabrevis.ch": seit ADR-0020 D3
        # kommt der Name aus der **Sitzung** und nicht aus dem Anfragekörper.
        # Der Testclient benutzt den Bootstrap-Token, und der heisst im
        # Protokoll so, damit er auffällt.
        assert response.json()["updated_by"] == "bootstrap-token"

    def test_a_secret_is_refused_with_422(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        response = _put(
            console_client,
            "/api/platform/settings",
            {"defaults": {"ad_bind_password": "hunter2"}},
        )
        assert response.status_code == 422
        # Die Meldung muss sagen, wohin es stattdessen gehört.
        assert "Anwendungsserver" in response.json()["detail"]

    def test_needs_a_token(self, client: TestClient, cockpit_schema: str) -> None:
        # `client` kommt durch den Management-Listener, aber ohne Token.
        assert client.get("/api/platform/settings").status_code == 401


class TestTenantOverrides:
    def test_no_overrides_is_an_empty_answer_not_404(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        response = console_client.get(f"/api/tenants/{tenant_row}/settings")
        assert response.status_code == 200
        assert response.json()["overrides"] == {}
        assert response.json()["updated_at"] is None

    def test_unknown_tenant_is_404(self, console_client: TestClient, cockpit_schema: str) -> None:
        assert console_client.get(f"/api/tenants/{uuid.uuid4()}/settings").status_code == 404

    def test_override_shows_up_in_the_desired_state(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        _put(
            console_client,
            "/api/platform/settings",
            {
                "defaults": {"ad_sync_interval_minutes": 60, "instance_profile": "school"},
            },
        )
        _put(
            console_client,
            f"/api/tenants/{tenant_row}/settings",
            {"overrides": {"ad_sync_interval_minutes": 15}},
        )
        state = console_client.get(f"/api/tenants/{tenant_row}/desired-state").json()
        assert state["settings"] == {
            "ad_sync_interval_minutes": 15,
            "instance_profile": "school",
        }
        assert state["settings_source"] == "tenant"

    def test_platform_rbac_applies_until_the_tenant_has_its_own(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        _put(
            console_client,
            "/api/platform/settings",
            {"rbac": {"kl": ["user.read"]}},
        )
        state = console_client.get(f"/api/tenants/{tenant_row}/desired-state").json()
        assert state["rbac"] == {"kl": ["user.read"]}
        assert state["rbac_source"] == "platform"

        _put(
            console_client,
            f"/api/tenants/{tenant_row}/settings",
            {"rbac": {"kl": ["user.read", "class.read"]}},
        )
        state = console_client.get(f"/api/tenants/{tenant_row}/desired-state").json()
        assert state["rbac"] == {"kl": ["user.read", "class.read"]}
        assert state["rbac_source"] == "tenant"

    def test_clear_rbac_goes_back_to_the_platform_matrix(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        """Der Weg zurück, den `rbac: null` nicht gehen kann.

        `null` heisst „nicht angefasst". Ohne den ausdrücklichen Schalter
        liesse sich eine eigene Matrix nie wieder aufgeben — und niemand
        merkt es, bis jemand es versucht.
        """
        _put(console_client, "/api/platform/settings", {"rbac": {"kl": ["user.read"]}})
        _put(
            console_client,
            f"/api/tenants/{tenant_row}/settings",
            {"rbac": {"kl": []}},
        )
        assert (
            console_client.get(f"/api/tenants/{tenant_row}/desired-state").json()["rbac_source"]
            == "tenant"
        )
        _put(
            console_client,
            f"/api/tenants/{tenant_row}/settings",
            {"clear_rbac": True},
        )
        state = console_client.get(f"/api/tenants/{tenant_row}/desired-state").json()
        assert state["rbac_source"] == "platform"
        assert state["rbac"] == {"kl": ["user.read"]}

    def test_an_empty_own_matrix_is_not_the_same_as_none(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        """`{}` heisst „eigene Matrix, und die ist leer" — das entrechtet.

        Der Unterschied steht in der Migration als `nullable=True` und muss
        über die ganze Kette halten, sonst ist er Zierrat.
        """
        _put(console_client, "/api/platform/settings", {"rbac": {"kl": ["user.read"]}})
        _put(
            console_client,
            f"/api/tenants/{tenant_row}/settings",
            {"rbac": {}},
        )
        state = console_client.get(f"/api/tenants/{tenant_row}/desired-state").json()
        assert state["rbac"] == {}
        assert state["rbac_source"] == "tenant"

    def test_a_secret_is_refused_for_a_tenant_too(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        response = _put(
            console_client,
            f"/api/tenants/{tenant_row}/settings",
            {"overrides": {"oidc_client_secret": "x"}},
        )
        assert response.status_code == 422
