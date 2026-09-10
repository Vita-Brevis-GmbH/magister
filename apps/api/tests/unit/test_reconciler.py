"""Abgleich des Soll-Zustands (ADR-0017 D3/D4).

Die Zusagen, die hier geprüft werden:

* **Nur die Differenz wird geschrieben.** Ein Abgleich, der nichts findet,
  schreibt nichts — keine Versionserhöhung, kein Audit-Ereignis. Ohne das
  wäre die Versionsnummer nach einem Monat achttausend.
* **Eine Vorgabe ist eine Aussage über die genannten Rollen**, nicht über
  alle. Sonst löschte eine Vorgabe mit zwei Rollen die eigenen Rollen des
  Kunden mit.
* **Ein unbrauchbarer Soll-Zustand wird nicht materialisiert.** Was in ein
  Kundenschema geschrieben wird, muss die erwartete Form haben.
"""

from __future__ import annotations

from typing import Any

import pytest

from magister_api.services.reconciler import (
    ORDER_MATTERS,
    RECONCILABLE,
    settings_diff,
)
from magister_api.tenancy.desired_state import (
    DesiredStateUnavailableError,
    parse_desired_state,
)


class TestParse:
    def test_the_normal_shape(self) -> None:
        state = parse_desired_state(
            {
                "settings": {"ad_sync_interval_minutes": 15},
                "rbac": {"kl": ["user.read"]},
                "settings_source": "tenant",
                "rbac_source": "platform",
            }
        )
        assert state.settings == {"ad_sync_interval_minutes": 15}
        assert state.rbac == {"kl": ["user.read"]}
        assert state.settings_source == "tenant"
        assert state.has_rbac

    def test_missing_settings_is_refused(self) -> None:
        # Nicht „dann eben leer": ein leerer Soll-Zustand, der als solcher
        # materialisiert wird, setzt einen Kunden zurück.
        with pytest.raises(DesiredStateUnavailableError, match="settings"):
            parse_desired_state({"rbac": {}})

    def test_a_list_of_tenants_is_not_a_desired_state(self) -> None:
        # Der Fall, der wirklich passiert: die falsche URL erwischt, und die
        # Registry-Antwort kommt zurück.
        with pytest.raises(DesiredStateUnavailableError, match="kein Objekt"):
            parse_desired_state([{"slug": "alpha"}])

    def test_a_malformed_rbac_entry_is_refused(self) -> None:
        with pytest.raises(DesiredStateUnavailableError, match="kl"):
            parse_desired_state({"settings": {}, "rbac": {"kl": "user.read"}})
        with pytest.raises(DesiredStateUnavailableError, match="Namensliste"):
            parse_desired_state({"settings": {}, "rbac": {"kl": [1, 2]}})

    def test_no_rbac_means_do_not_touch_it(self) -> None:
        state = parse_desired_state({"settings": {}, "rbac": {}})
        assert not state.has_rbac


class TestSettingsDiff:
    def test_nothing_changed_is_an_empty_diff(self) -> None:
        current = {"ad_sync_interval_minutes": 60, "instance_profile": "school"}
        assert settings_diff(current, dict(current)) == {}

    def test_a_change_carries_old_and_new(self) -> None:
        diff = settings_diff({"ad_sync_interval_minutes": 60}, {"ad_sync_interval_minutes": 15})
        assert diff == {"ad_sync_interval_minutes": (60, 15)}

    def test_a_reordered_list_is_not_a_change(self) -> None:
        """Sonst schreibt der Abgleich bei jedem Lauf.

        Postgres gibt eine Liste in der Reihenfolge zurück, in der sie
        gespeichert wurde; die Konsole in der, in der sie getippt wurde. Ohne
        diese Regel wäre jede Runde eine Änderung — mit Audit-Ereignis.
        """
        diff = settings_diff({"mail_domains": ["a.ch", "b.ch"]}, {"mail_domains": ["b.ch", "a.ch"]})
        assert diff == {}

    def test_but_the_dc_order_does_matter(self) -> None:
        # `ad_dcs` ist die Vorrangliste des ServerPools: eine andere
        # Reihenfolge ist eine andere Konfiguration.
        diff = settings_diff({"ad_dcs": ["dc1", "dc2"]}, {"ad_dcs": ["dc2", "dc1"]})
        assert diff == {"ad_dcs": (["dc1", "dc2"], ["dc2", "dc1"])}
        assert "ad_dcs" in ORDER_MATTERS

    def test_a_missing_current_value_is_a_change(self) -> None:
        diff = settings_diff({}, {"oidc_issuer": "https://login.example"})
        assert diff == {"oidc_issuer": (None, "https://login.example")}


class TestReconcilableIsSafe:
    """Was der Abgleich schreiben darf, darf kein Geheimnis sein."""

    def test_no_encrypted_column_is_reconcilable(self) -> None:
        offenders = [k for k in RECONCILABLE if k.endswith("_enc")]
        assert offenders == [], f"Der Abgleich würde verschlüsselte Spalten schreiben: {offenders}"

    def test_the_four_secrets_are_not_reconcilable(self) -> None:
        for secret in (
            "oidc_client_secret",
            "ad_bind_password",
            "ninja_client_secret",
            "web_tls_key_pem",
        ):
            assert secret not in RECONCILABLE

    def test_every_reconcilable_key_exists_on_the_model(self) -> None:
        """Ein Tippfehler in der Liste fällt hier auf, nicht im Betrieb.

        Der Abgleich liest die Spalten über `getattr(AppSettings, key)`. Ein
        falscher Name wäre ein `AttributeError` mitten in der
        Hintergrundschleife — sichtbar nur im Log, und nur bei einem Kunden mit
        Konsolen-Id.
        """
        from magister_api.models.app_settings import AppSettings

        missing = [k for k in RECONCILABLE if not hasattr(AppSettings, k)]
        assert missing == [], f"Diese Felder gibt es in app_settings nicht: {missing}"

    def test_the_console_allowlist_and_this_one_agree(self) -> None:
        """Beide Listen nennen dieselben Felder.

        Sie stehen in zwei Repositories (Konsole und Datenebene) und werden
        nicht voneinander importiert — die Datenebene darf nicht von der
        Konsole abhängen. Also prüft dieser Test die Übereinstimmung, und
        zwar nachsichtig in eine Richtung: die Konsole darf ein Feld kennen,
        das diese Datenebene noch nicht hat (sie ist möglicherweise neuer, und
        der Abgleich verwirft es mit einer Meldung). Umgekehrt wäre es ein
        Feld, das nie ankommt.
        """
        console_keys = _console_policy_keys()
        if console_keys is None:
            pytest.skip("Konsole nicht im Pfad — läuft in CI mit beiden Paketen")
        never_arrives = sorted(RECONCILABLE - console_keys)
        assert never_arrives == [], (
            f"Diese Felder gleicht die Datenebene ab, aber die Konsole kann sie "
            f"nicht setzen: {never_arrives}"
        )


def _console_policy_keys() -> set[str] | None:
    """Die Allowlist der Konsole, wenn sie erreichbar ist.

    Über den Dateipfad und nicht über einen Import: die Datenebene hat
    `cockpit_api` nicht als Abhängigkeit, und das soll so bleiben — die
    Konsole ist ein eigenes Paket und wird später ein eigenes Repository.
    """
    import ast
    from pathlib import Path

    # tests/unit/x.py -> tests -> apps/api -> apps -> Repository-Wurzel
    candidate = (
        Path(__file__).resolve().parents[4]
        / "cockpit"
        / "api"
        / "cockpit_api"
        / "services"
        / "settings.py"
    )
    if not candidate.is_file():
        return None
    tree = ast.parse(candidate.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "POLICY_KEYS" and isinstance(node.value, ast.Dict):
                keys: set[str] = set()
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
                return keys
    return None


class TestDesiredStateUrl:
    """Eine Einstellung und nicht zwei.

    Zwei URLs, die auf dieselbe Konsole zeigen sollen, zeigen irgendwann auf
    verschiedene. Der Pfad des Soll-Zustands wird deshalb aus der
    Registry-Adresse abgeleitet — und das wird hier über einen echten Aufruf
    gegen einen abgefangenen Transport geprüft, nicht über den Quelltext.
    """

    @pytest.mark.asyncio
    async def test_the_path_is_derived_from_the_registry_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        from magister_api.tenancy import desired_state as mod

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"settings": {}, "rbac": {}})

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = transport
            return real_client(**kwargs)

        monkeypatch.setattr(mod.httpx, "AsyncClient", factory)
        await mod.fetch_desired_state(
            "https://console.intern:4444/api/tenants/registry",
            "11111111-1111-1111-1111-111111111111",
            token="t",
        )

        assert seen == [
            "https://console.intern:4444/api/tenants/"
            "11111111-1111-1111-1111-111111111111/desired-state"
        ]

    @pytest.mark.asyncio
    async def test_an_http_error_does_not_leak_the_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Die Meldung geht in den Log — dort hat ein Token nichts zu suchen."""
        import httpx

        from magister_api.tenancy import desired_state as mod

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="nope")

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = transport
            return real_client(**kwargs)

        monkeypatch.setattr(mod.httpx, "AsyncClient", factory)
        with pytest.raises(DesiredStateUnavailableError) as excinfo:
            await mod.fetch_desired_state(
                "https://console.intern:4444/api/tenants/registry",
                "abc",
                token="streng-geheim",
            )
        assert "streng-geheim" not in str(excinfo.value)
        assert "403" in str(excinfo.value)
