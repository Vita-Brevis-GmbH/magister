"""Bausteine von ADR-0024 ohne Datenbank: Soll-Zustand, AD-Bereitschaft, Schlüssel."""

from __future__ import annotations

import pytest

from magister_api.ad.factory import ad_missing_settings
from magister_api.config import Settings
from magister_api.tenancy.desired_state import (
    DesiredStateUnavailableError,
    parse_desired_state,
)
from magister_api.tenancy.sealing import UnsealError, key_id, public_key_b64, unseal

BASE = dict(audit_key="k" * 32, session_secret="s" * 32, csrf_secret="c" * 32)


class TestDesiredStateParsing:
    def test_sealed_and_maintenance(self) -> None:
        state = parse_desired_state(
            {
                "settings": {},
                "sealed_secrets": {"oidc_client_secret": "v1.abc"},
                "maintenance": [
                    {"id": "r1", "action": "demo_purge", "requested_by": "ops", "reason": "x"}
                ],
            }
        )
        assert state.sealed_secrets == {"oidc_client_secret": "v1.abc"}
        assert state.maintenance[0].id == "r1"
        assert state.maintenance[0].action == "demo_purge"

    def test_an_older_console_without_the_fields(self) -> None:
        state = parse_desired_state({"settings": {}})
        assert state.sealed_secrets == {}
        assert state.maintenance == ()

    @pytest.mark.parametrize(
        "payload",
        [
            {"settings": {}, "sealed_secrets": ["x"]},
            {"settings": {}, "maintenance": {"id": "r1"}},
            {"settings": {}, "maintenance": [{"action": "demo_purge"}]},
        ],
    )
    def test_wrong_shapes_are_refused(self, payload: dict[str, object]) -> None:
        with pytest.raises(DesiredStateUnavailableError):
            parse_desired_state(payload)


class TestAdReadiness:
    def test_connector_needs_no_domain_controller(self) -> None:
        """Gehostet kennt der Agent die DCs; verlangt wurden sie trotzdem."""
        effective = Settings(**BASE, ad_users_search_base="OU=U,DC=x", ad_dcs=[])  # type: ignore[arg-type]
        assert ad_missing_settings(effective, "connector") == []
        assert ad_missing_settings(effective, "ldap") == ["ad_dcs"]

    def test_search_base_is_always_needed(self) -> None:
        effective = Settings(**BASE, ad_users_search_base="")  # type: ignore[arg-type]
        assert "ad_users_search_base" in ad_missing_settings(effective, "connector")


class TestKeypair:
    def test_derived_and_stable(self) -> None:
        a, b = public_key_b64("schluessel-a" * 3), public_key_b64("schluessel-a" * 3)
        assert a == b
        assert public_key_b64("schluessel-b" * 3) != a
        assert len(key_id(a)) == 16

    def test_garbage_does_not_open(self) -> None:
        with pytest.raises(UnsealError):
            unseal("k" * 32, "v1.kaputt", tenant_ref="t", name="oidc_client_secret")
        with pytest.raises(UnsealError):
            unseal("k" * 32, "v9.abc", tenant_ref="t", name="oidc_client_secret")
