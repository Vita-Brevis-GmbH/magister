"""Selbstprüfung der Anmeldung über den Realm (ADR-0025 Nachtrag 2026-11-16).

Fund aus dem Test: Magister hatte als Issuer die interne Keycloak-Adresse,
deren Zertifikat es nicht vertraute — sichtbar erst beim Anmelden
(`oidc_discovery_failed`). Die Selbstprüfung meldet das mit der
Zustandsmeldung ans Cockpit, mit einem Grund, der sagt, woran es liegt.

Gegen ein Keycloak-förmiges Dokument (MockTransport), und für den Fund gegen
einen echten TLS-Server mit einem Zertifikat aus einer fremden CA.
"""

from __future__ import annotations

import json
import socket
import ssl
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from magister_api.auth.oidc import OidcDiscoveryError, StandardOidcClient, failure_kind
from magister_api.auth.oidc_check import REASON_MAX, check_oidc
from magister_api.config import Settings
from tests.pki import write_pki

ISSUER = "https://sso.example.ch/realms/kunde-a"
BASE = f"{ISSUER}/protocol/openid-connect"
DISCOVERY: dict[str, Any] = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{BASE}/auth",
    "token_endpoint": f"{BASE}/token",
    "jwks_uri": f"{BASE}/certs",
    "end_session_endpoint": f"{BASE}/logout",
}
JWKS = {"keys": [{"kty": "RSA", "kid": "k1", "n": "AQAB", "e": "AQAB"}]}
SECRET = "nur-test-client-secret"

Handler = Callable[[httpx.Request], httpx.Response]


def _settings(
    issuer: str = ISSUER, *, client_id: str = "magister", secret: str = SECRET
) -> Settings:
    return Settings(
        oidc_issuer=issuer,
        oidc_client_id=client_id,
        oidc_client_secret=SecretStr(secret),
    )


def _provider(
    *, discovery: Any = None, discovery_status: int = 200, jwks: Any = None, jwks_status: int = 200
) -> Handler:
    doc = DISCOVERY if discovery is None else discovery
    keys = JWKS if jwks is None else jwks

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            if isinstance(doc, str):
                return httpx.Response(discovery_status, text=doc)
            return httpx.Response(discovery_status, json=doc)
        if request.url.path.endswith("/certs"):
            return httpx.Response(jwks_status, json=keys)
        return httpx.Response(404)

    return handler


async def _check(handler: Handler, settings: Settings | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        return await check_oidc(settings or _settings(), http=http)


class TestShape:
    async def test_not_configured_is_no_finding(self) -> None:
        result = await check_oidc(_settings(issuer="", client_id=""))
        assert result == {"configured": False, "ok": None, "reason": None, "checked_at": None}

    async def test_ok_has_exactly_the_four_fields(self) -> None:
        result = await _check(_provider())
        assert set(result) == {"configured", "ok", "reason", "checked_at"}
        assert result["configured"] is True
        assert result["ok"] is True
        assert result["reason"] is None
        assert datetime.fromisoformat(result["checked_at"]).tzinfo is not None

    async def test_a_trailing_slash_in_the_setting_is_no_mismatch(self) -> None:
        assert (await _check(_provider(), _settings(f"{ISSUER}/")))["ok"] is True

    async def test_the_secret_never_appears(self) -> None:
        for handler in (_provider(), _provider(discovery_status=500)):
            assert SECRET not in json.dumps(await _check(handler))


class TestReasons:
    @pytest.mark.parametrize(
        ("handler", "reason"),
        [
            (_provider(discovery_status=404), "discovery_http_404 (sso.example.ch)"),
            (_provider(discovery="<html>kein JSON</html>"), "discovery_invalid (sso.example.ch)"),
            (_provider(discovery=["kein", "Objekt"]), "discovery_invalid (sso.example.ch)"),
            (
                _provider(discovery={k: v for k, v in DISCOVERY.items() if k != "jwks_uri"}),
                "discovery_incomplete: jwks_uri (sso.example.ch)",
            ),
            (_provider(jwks_status=500), "jwks_failed: http_500 (sso.example.ch)"),
            (_provider(jwks={"keys": []}), "jwks_failed: no_keys (sso.example.ch)"),
        ],
    )
    async def test_reason(self, handler: Handler, reason: str) -> None:
        result = await _check(handler)
        assert result["configured"] is True
        assert result["ok"] is False
        assert result["reason"] == reason

    async def test_the_realm_names_another_issuer(self) -> None:
        """Keycloak nennt den Issuer nach seinem Hostnamen, nicht nach der gefragten Adresse."""
        public = "https://auth.example.ch/realms/kunde-a"
        doc = {**DISCOVERY, "issuer": public}
        result = await _check(_provider(discovery=doc))
        assert result["reason"] == f"issuer_mismatch: {public} (sso.example.ch)"

    async def test_without_a_client_secret(self) -> None:
        result = await _check(_provider(), _settings(secret=""))
        assert (result["ok"], result["reason"]) == (False, "client_secret_missing")

    async def test_the_first_problem_wins(self) -> None:
        # Kein Realm und kein Secret: die Discovery ist der grundlegendere Fehler.
        result = await _check(_provider(discovery_status=404), _settings(secret=""))
        assert result["reason"] == "discovery_http_404 (sso.example.ch)"

    async def test_name_resolution(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            try:
                raise socket.gaierror(-2, "Name or service not known")
            except socket.gaierror as exc:
                raise httpx.ConnectError(str(exc)) from exc

        assert (await _check(handler))["reason"] == "discovery_dns (sso.example.ch)"

    async def test_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("zu langsam")

        assert (await _check(handler))["reason"] == "discovery_timeout (sso.example.ch)"

    async def test_a_port_is_part_of_the_host_and_no_user_part(self) -> None:
        settings = _settings("https://jemand:geheim@kc.example.ch:8443/realms/kunde-a")
        result = await _check(_provider(discovery_status=404), settings)
        assert result["reason"] == "discovery_http_404 (kc.example.ch:8443)"
        assert "geheim" not in json.dumps(result)

    async def test_the_reason_is_at_most_300_characters(self) -> None:
        doc = {**DISCOVERY, "issuer": "https://auth.example.ch/" + "x" * 400}
        result = await _check(_provider(discovery=doc))
        assert result["reason"].startswith("issuer_mismatch: ")
        assert len(result["reason"]) <= REASON_MAX

    async def test_a_broken_check_is_reported_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("kaputt")

        result = await _check(handler)
        assert (result["ok"], result["reason"]) == (False, "check_failed: RuntimeError")


class _Discovery(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(DISCOVERY).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def untrusted_provider(tmp_path: Path) -> Iterator[str]:
    """Ein Anbieter mit einem Zertifikat aus einer CA, der Magister nicht vertraut."""
    _, cert, key = write_pki(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), _Discovery)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_address[1]}/realms/kunde-a"
    finally:
        server.shutdown()
        server.server_close()


class TestTheFinding:
    async def test_an_untrusted_certificate_is_named(self, untrusted_provider: str) -> None:
        """Der Fund vom 2026-11-16 — jetzt in der Zustandsmeldung statt erst beim Anmelden."""
        result = await check_oidc(_settings(untrusted_provider))
        port = untrusted_provider.split(":")[2].split("/")[0]
        assert result["ok"] is False
        assert result["reason"].startswith("discovery_tls: CERTIFICATE_VERIFY_FAILED")
        assert result["reason"].endswith(f"(127.0.0.1:{port})")

    async def test_the_login_still_gets_its_code(self, untrusted_provider: str) -> None:
        """Für die Anmeldeseite bleibt es `oidc_discovery_failed`; der Grund steht daneben."""
        client = StandardOidcClient(_settings(untrusted_provider))
        with pytest.raises(OidcDiscoveryError, match="^oidc_discovery_failed$") as caught:
            await client.build_authorize_request()
        assert caught.value.reason.startswith("discovery_tls: CERTIFICATE_VERIFY_FAILED")


class TestFailureKind:
    def test_a_refused_connection(self) -> None:
        try:
            try:
                raise ConnectionRefusedError(111, "Connection refused")
            except ConnectionRefusedError as inner:
                raise OSError("All connection attempts failed") from inner
        except OSError as exc:
            wrapped = httpx.ConnectError(str(exc))
            wrapped.__cause__ = exc
        assert failure_kind(wrapped) == "connect: refused"

    def test_a_proxy_that_does_not_forward(self) -> None:
        assert failure_kind(httpx.ProxyError("502")) == "proxy"

    def test_plain_http_on_a_tls_port(self) -> None:
        inner = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")
        inner.reason = "WRONG_VERSION_NUMBER"  # pyright: ignore[reportAttributeAccessIssue]
        wrapped = httpx.ConnectError("wrong version number")
        wrapped.__cause__ = inner
        assert failure_kind(wrapped) == "tls: WRONG_VERSION_NUMBER"
