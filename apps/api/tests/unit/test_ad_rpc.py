"""Strict AD boundary (ADR-0011): serialization, RPC client, RPC server.

All DB-free. The client is exercised against an httpx MockTransport; the server
dispatch against an in-process ASGI transport with ``get_ad_client`` overridden
to a fake directory, so no real AD (or Postgres) is needed.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.ad.errors import AdUnavailableError
from magister_api.ad.rpc import (
    ALLOWED_METHODS,
    RPC_PATH,
    SECRET_HEADER,
    ad_user_record_from_jsonable,
    ad_user_record_to_jsonable,
)
from magister_api.ad.rpc_client import AdRpcClient
from magister_api.config import Settings
from magister_api.main import create_app
from magister_api.routers.admin_sync import get_ad_client


def _record() -> AdUserRecord:
    return AdUserRecord(
        ad_object_guid="11111111-1111-1111-1111-111111111111",
        upn="a@b.ch",
        sam_account_name="ab",
        given_name="A",
        surname="B",
        display_name="A B",
        mail="a@b.ch",
        enabled=True,
        kind="teacher",
        password_never_expires=False,
        ms_ds_consistency_guid=None,
        distinguished_name="CN=A B,OU=x,DC=b,DC=ch",
        street_address=None,
        locality=None,
        postal_code=None,
        country=None,
        when_changed=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        groups=("CN=g1,DC=b,DC=ch", "CN=g2,DC=b,DC=ch"),
        mail_aliases=("alias@b.ch",),
    )


# --- serialization ---------------------------------------------------------------


def test_ad_user_record_roundtrip() -> None:
    rec = _record()
    restored = ad_user_record_from_jsonable(ad_user_record_to_jsonable(rec))
    assert restored == rec
    assert restored.when_changed == rec.when_changed
    assert restored.groups == rec.groups  # tuples preserved, not lists


# --- contract: RPC surface stays in lockstep with AdClient -----------------------


def _param_shape(fn: Any) -> list[tuple[str, Any]]:
    # Parameter names + kinds — catches added/removed/renamed/reordered params
    # without being brittle about annotations or default values.
    return [(p.name, p.kind) for p in inspect.signature(fn).parameters.values()]


def test_allowed_methods_are_async_on_adclient() -> None:
    for name in ALLOWED_METHODS:
        fn = getattr(AdClient, name, None)
        assert fn is not None, f"ALLOWED_METHODS names {name!r} but AdClient has no such method"
        assert inspect.iscoroutinefunction(fn), f"{name} must be async"


def test_rpc_client_overrides_every_allowed_method() -> None:
    # Each RPC method must be defined ON AdRpcClient (forwarding), not inherited
    # from AdClient — otherwise a client container would try to hit AD directly.
    for name in ALLOWED_METHODS:
        assert name in AdRpcClient.__dict__, f"{name} is not overridden on AdRpcClient"


def test_rpc_client_signatures_match_adclient() -> None:
    # If an AdClient method gains/renames a parameter but the AdRpcClient override
    # is not updated, the RPC would silently forward the wrong kwargs. Lock it.
    for name in ALLOWED_METHODS:
        parent = _param_shape(getattr(AdClient, name))
        child = _param_shape(getattr(AdRpcClient, name))
        assert child == parent, f"signature drift on {name}: {child} != {parent}"


def test_sync_methods_are_not_on_the_rpc_surface() -> None:
    # The recurring AD reads run only in the ad container, never over RPC.
    for name in ("search_users", "search_groups", "search_computers"):
        assert name not in ALLOWED_METHODS


# --- RPC client (httpx MockTransport) --------------------------------------------


def _client(handler: Any, *, secret: str = "s3cr3t") -> AdRpcClient:
    return AdRpcClient(
        Settings(),
        base_url="http://magister-api-ad:8000",
        secret=secret,
        transport=httpx.MockTransport(handler),
    )


async def test_client_forwards_and_deserializes_record() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get(SECRET_HEADER)
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": ad_user_record_to_jsonable(_record())})

    client = _client(handler)
    try:
        rec = await client.authenticate(login="a@b.ch", password="pw")
    finally:
        await client.aclose()
    assert rec == _record()
    assert seen["url"] == f"http://magister-api-ad:8000{RPC_PATH}/authenticate"
    assert seen["secret"] == "s3cr3t"
    assert seen["body"] == {"login": "a@b.ch", "password": "pw"}


async def test_client_authenticate_none() -> None:
    client = _client(lambda r: httpx.Response(200, json={"result": None}))
    try:
        assert await client.authenticate(login="x", password="y") is None
    finally:
        await client.aclose()


async def test_client_tuple_and_list_returns() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/set_account_enabled"):
            return httpx.Response(200, json={"result": [True, False]})
        return httpx.Response(200, json={"result": ["CN=failed,DC=b"]})

    client = _client(handler)
    try:
        assert await client.set_account_enabled(user_dn="CN=x", enabled=False) == (True, False)
        failed = await client.add_user_to_groups(user_dn="CN=x", group_dns=["CN=g"])
        assert failed == ["CN=failed,DC=b"]
    finally:
        await client.aclose()


async def test_client_maps_server_error_to_exception() -> None:
    client = _client(
        lambda r: httpx.Response(
            502, json={"error_type": "AdUnavailableError", "detail": "ldap_modify_failed:x"}
        )
    )
    try:
        with pytest.raises(AdUnavailableError, match="ldap_modify_failed"):
            await client.modify_password(user_dn="CN=x", new_password="p", force_change=True)
    finally:
        await client.aclose()


async def test_client_network_failure_is_ad_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = _client(handler)
    try:
        with pytest.raises(AdUnavailableError, match="ad_rpc_unreachable"):
            await client.find_user_dn("guid")
    finally:
        await client.aclose()


# --- RPC server (ASGI transport, no DB) ------------------------------------------


class _FakeAd:
    async def find_user_dn(self, *, ad_object_guid: str) -> str | None:
        return f"CN={ad_object_guid}"

    async def authenticate(self, *, login: str, password: str) -> AdUserRecord | None:
        return _record() if password == "good" else None

    async def modify_password(self, *, user_dn: str, new_password: str, force_change: bool) -> None:
        raise AdUnavailableError("ldap_modify_failed:denied")


def _server_client(secret: str | None = "sec") -> tuple[httpx.AsyncClient, Any]:
    app = create_app(Settings(ad_rpc_secret=SecretStr(secret)) if secret else Settings())
    app.dependency_overrides[get_ad_client] = lambda: _FakeAd()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://internal"), app


async def _post(method: str, body: dict[str, Any], *, header: str | None = "sec") -> httpx.Response:
    client, _ = _server_client()
    headers = {SECRET_HEADER: header} if header is not None else {}
    try:
        return await client.post(f"{RPC_PATH}/{method}", json=body, headers=headers)
    finally:
        await client.aclose()


async def test_server_dispatches_and_serializes() -> None:
    r = await _post("find_user_dn", {"ad_object_guid": "g1"})
    assert r.status_code == 200
    assert r.json() == {"result": "CN=g1"}

    r = await _post("authenticate", {"login": "a", "password": "good"})
    assert r.status_code == 200
    assert ad_user_record_from_jsonable(r.json()["result"]) == _record()


async def test_server_rejects_wrong_secret() -> None:
    assert (await _post("find_user_dn", {"ad_object_guid": "g"}, header="nope")).status_code == 403
    assert (await _post("find_user_dn", {"ad_object_guid": "g"}, header=None)).status_code == 403


async def test_server_rejects_unknown_method() -> None:
    # search_users is a real AdClient method but NOT on the RPC allowlist.
    assert (await _post("search_users", {})).status_code == 404
    assert (await _post("__init__", {})).status_code == 404


async def test_server_maps_ad_error_to_502() -> None:
    r = await _post(
        "modify_password", {"user_dn": "CN=x", "new_password": "p", "force_change": True}
    )
    assert r.status_code == 502
    assert r.json()["error_type"] == "AdUnavailableError"
    assert "ldap_modify_failed" in r.json()["detail"]


async def test_server_not_mounted_when_rpc_client() -> None:
    # A client container (MAGISTER_AD_RPC_URL set) must NOT expose the server.
    app = create_app(
        Settings(ad_rpc_url="http://magister-api-ad:8000", ad_rpc_secret=SecretStr("sec"))
    )
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(str(p).startswith(RPC_PATH) for p in paths)


def test_server_mounted_when_url_blank() -> None:
    # The AD owner blanks MAGISTER_AD_RPC_URL via a compose override; empty must
    # count as AD-capable (server mounted), same as unset.
    for blank in (None, ""):
        app = create_app(Settings(ad_rpc_url=blank, ad_rpc_secret=SecretStr("sec")))
        paths = {str(getattr(r, "path", "")) for r in app.routes}
        assert any(p.startswith(RPC_PATH) for p in paths), f"url={blank!r}"
