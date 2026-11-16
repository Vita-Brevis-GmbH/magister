"""Die Datenebene vertraut der Konsole über die Plattform-CA (Befund Dev-Host).

Gegen einen echten TLS-Server mit einem Zertifikat aus einer Test-CA: genau
die Lage auf dem Dev-Host. Ohne ``MAGISTER_CONSOLE_CA_FILE`` scheiterte dort
jeder Abruf an ``CERTIFICATE_VERIFY_FAILED``. Die Datenebene fiel still auf
ihren Ersatz-Mandanten zurück, und der Kunde lief im falschen Schema.
"""

from __future__ import annotations

import json
import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from magister_api.config import Settings
from magister_api.tenancy import console_tls
from magister_api.tenancy.console_tls import ConsoleTlsError, console_verify
from magister_api.tenancy.context import build_registry
from magister_api.tenancy.desired_state import DesiredStateUnavailableError, fetch_desired_state
from magister_api.tenancy.registry import TenantStatus
from tests.pki import write_pki


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"settings": {"instance_profile": "company"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def console(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    root, cert, key = write_pki(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_address[1]}", root
    finally:
        server.shutdown()
        server.server_close()


def _use(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    settings = Settings(**values)  # type: ignore[arg-type]
    monkeypatch.setattr(console_tls, "get_settings", lambda: settings)
    console_tls._context.cache_clear()  # pyright: ignore[reportPrivateUsage]


class TestTrust:
    async def test_without_the_platform_ca_the_console_is_not_trusted(
        self, console: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, _ = console
        _use(monkeypatch, console_ca_file="")
        with pytest.raises(DesiredStateUnavailableError, match="CERTIFICATE_VERIFY_FAILED"):
            await fetch_desired_state(f"{base}/api/tenants/registry", "t-1", token="x")

    async def test_with_the_platform_ca_it_is(
        self, console: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, root = console
        _use(monkeypatch, console_ca_file=str(root))
        state = await fetch_desired_state(f"{base}/api/tenants/registry", "t-1", token="x")
        assert state.settings == {"instance_profile": "company"}

    def test_a_missing_file_is_named(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _use(monkeypatch, console_ca_file=str(tmp_path / "fehlt.pem"))
        with pytest.raises(ConsoleTlsError, match="fehlt.pem"):
            console_verify()

    async def test_a_missing_file_is_an_unreachable_console_not_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, console_ca_file=str(tmp_path / "fehlt.pem"))
        with pytest.raises(DesiredStateUnavailableError, match="MAGISTER_CONSOLE_CA_FILE"):
            await fetch_desired_state("https://127.0.0.1:1/api/tenants/registry", "t-1", token="x")


class TestHostedFallbackServesNobody:
    def test_hosted_without_a_tenant_list_is_provisioning(self) -> None:
        """Gehostet und ohne Antwort der Konsole: kein Kunde im Schema public."""
        registry = build_registry(
            Settings(console_registry_url="https://konsole.invalid/api/tenants/registry")  # type: ignore[call-arg]
        )
        (tenant,) = registry.tenants
        assert tenant.schema_name == "public"
        assert tenant.status is TenantStatus.PROVISIONING
        assert not tenant.status.serves_requests

    def test_on_prem_stays_as_it_was(self) -> None:
        registry = build_registry(Settings(console_registry_url=""))  # type: ignore[call-arg]
        (tenant,) = registry.tenants
        assert tenant.status is TenantStatus.ACTIVE
