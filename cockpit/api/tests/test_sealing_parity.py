"""Konsole versiegelt, Datenebene öffnet (ADR-0024 D3).

Die beiden Hälften stehen in verschiedenen Paketen und dürfen sich nicht
importieren. Also wird die Datei der Datenebene geladen und die Rechnung über
die Grenze geprüft — samt der Fälle, die scheitern MÜSSEN: falscher Kunde,
falsches Feld, falscher Schlüssel, verändertes Chiffrat.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from cockpit_api.services.sealing import (
    ONE_TIME_SEALABLE,
    SEALABLE,
    SealingError,
    key_id,
    seal,
)


def _load() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "api"
        / "magister_api"
        / "tenancy"
        / "sealing.py"
    )
    if not path.is_file():
        pytest.skip(f"Datenebene nicht gefunden: {path}")
    spec = importlib.util.spec_from_file_location("dataplane_sealing", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dp = _load()
KEY = "kundenschluessel-" + "x" * 32
TENANT = "11111111-2222-3333-4444-555555555555"


def test_same_allowlist() -> None:
    assert dp.SEALABLE == SEALABLE
    assert dp.ONE_TIME_SEALABLE == ONE_TIME_SEALABLE


def test_roundtrip() -> None:
    public = dp.public_key_b64(KEY)
    blob = seal(public, "geheim-123", tenant_ref=TENANT, name="oidc_client_secret")
    assert "geheim-123" not in blob
    assert dp.unseal(KEY, blob, tenant_ref=TENANT, name="oidc_client_secret") == "geheim-123"


def test_same_fingerprint() -> None:
    public = dp.public_key_b64(KEY)
    assert key_id(public) == dp.key_id(public)


def test_each_sealing_is_different() -> None:
    public = dp.public_key_b64(KEY)
    a = seal(public, "x", tenant_ref=TENANT, name="oidc_client_secret")
    b = seal(public, "x", tenant_ref=TENANT, name="oidc_client_secret")
    assert a != b


@pytest.mark.parametrize(
    ("key", "tenant", "name"),
    [
        ("anderer-kundenschluessel-" + "y" * 24, TENANT, "oidc_client_secret"),
        (KEY, "99999999-2222-3333-4444-555555555555", "oidc_client_secret"),
        (KEY, TENANT, "ninja_client_secret"),
    ],
)
def test_wrong_key_tenant_or_field_does_not_open(key: str, tenant: str, name: str) -> None:
    public = dp.public_key_b64(KEY)
    blob = seal(public, "geheim", tenant_ref=TENANT, name="oidc_client_secret")
    with pytest.raises(dp.UnsealError):
        dp.unseal(key, blob, tenant_ref=tenant, name=name)


def test_tampered_ciphertext_does_not_open() -> None:
    public = dp.public_key_b64(KEY)
    blob = seal(public, "geheim", tenant_ref=TENANT, name="oidc_client_secret")
    tampered = blob[:-3] + ("A" if blob[-3] != "A" else "B") + blob[-2:]
    with pytest.raises(dp.UnsealError):
        dp.unseal(KEY, tampered, tenant_ref=TENANT, name="oidc_client_secret")


def test_unknown_field_is_refused_by_the_data_plane() -> None:
    public = dp.public_key_b64(KEY)
    blob = seal(public, "geheim", tenant_ref=TENANT, name="web_tls_key")
    with pytest.raises(dp.UnsealError):
        dp.unseal(KEY, blob, tenant_ref=TENANT, name="web_tls_key")


def test_invalid_public_key() -> None:
    with pytest.raises(SealingError):
        seal("kaputt", "x", tenant_ref=TENANT, name="oidc_client_secret")
