"""Service-account bind-mode selection (simple vs GSSAPI/Kerberos)."""

from __future__ import annotations

import pytest
from ldap3 import GSSAPI, SASL, SIMPLE
from pydantic import ValidationError

from magister_api.ad.client import _service_bind_kwargs
from magister_api.ad.errors import AdUnavailableError
from magister_api.config import Settings


def _settings(**kw: object) -> Settings:
    return Settings(**kw)  # type: ignore[arg-type]


class TestServiceBindKwargs:
    def test_simple_uses_dn_and_password(self) -> None:
        s = _settings(
            ad_bind_mode="simple",
            ad_bind_dn="cn=svc,dc=schule,dc=local",
            ad_bind_password="secret",  # noqa: S106 - test value
        )
        kw = _service_bind_kwargs(s)
        assert kw["authentication"] == SIMPLE
        assert kw["user"] == "cn=svc,dc=schule,dc=local"
        assert kw["password"] == "secret"
        assert "sasl_mechanism" not in kw

    def test_simple_missing_credentials_raises(self) -> None:
        s = _settings(ad_bind_mode="simple", ad_bind_dn=None, ad_bind_password=None)
        with pytest.raises(AdUnavailableError):
            _service_bind_kwargs(s)

    def test_gssapi_carries_no_password(self) -> None:
        # No bind DN / password configured — GSSAPI must not need them.
        s = _settings(ad_bind_mode="gssapi", ad_bind_dn=None, ad_bind_password=None)
        kw = _service_bind_kwargs(s)
        assert kw == {"authentication": SASL, "sasl_mechanism": GSSAPI}
        assert "password" not in kw
        assert "user" not in kw


def test_invalid_bind_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(ad_bind_mode="ntlm")
