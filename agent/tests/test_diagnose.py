"""Verbindungsfehler werden nach Ursache benannt (Zertifikat, Netz, DNS).

Gegen einen echten TLS-Server auf ``127.0.0.1`` und nicht gegen
``MockTransport``: der Fehler, um den es geht, entsteht in OpenSSL beim
Namensvergleich, und den überspringt jede Attrappe.
"""

from __future__ import annotations

import socket
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from connector_agent.config import AgentConfig
from connector_agent.diagnose import (
    explain_transport_error,
    ip_endpoint_hint,
    probe_channel,
)
from connector_agent.enrollment import EnrollmentFailedError, enroll
from tests.helpers import FakeCa


class _TlsServer:
    """Nimmt Verbindungen an und führt den Handshake. Mehr nicht."""

    def __init__(self, cert: Path, key: Path, *, client_ca: Path | None = None) -> None:
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        if client_ca is not None:
            self.context.verify_mode = ssl.CERT_REQUIRED
            self.context.load_verify_locations(cafile=str(client_ca))
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.sock.settimeout(0.2)
        self.port: int = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                continue
            try:
                with self.context.wrap_socket(conn, server_side=True) as tls:
                    tls.settimeout(1.0)
                    try:
                        tls.recv(1)
                    except (OSError, ssl.SSLError):
                        pass
            except (OSError, ssl.SSLError):
                conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


@pytest.fixture
def ca() -> FakeCa:
    return FakeCa()


@pytest.fixture
def server(ca: FakeCa, tmp_path: Path) -> Iterator[_TlsServer]:
    cert_pem, key_pem = ca.issue_server("localhost")
    cert, key = tmp_path / "server.pem", tmp_path / "server-key.pem"
    cert.write_text(cert_pem)
    key.write_text(key_pem)
    srv = _TlsServer(cert, key)
    yield srv
    srv.close()


def _config(tmp_path: Path, endpoint: str, ca_pem: str, *, proxy: str | None = None) -> AgentConfig:
    bundle = tmp_path / "ca.pem"
    bundle.write_text(ca_pem)
    mapping: dict[str, object] = {
        "endpoint": endpoint,
        "state_dir": str(tmp_path / "state"),
        "ca_bundle": str(bundle),
        "allowed_ous": ["OU=Schule,DC=x,DC=y"],
    }
    if proxy:
        mapping["proxy"] = proxy
    return AgentConfig.from_mapping(mapping)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


class TestTheRightNameWorks:
    def test_probe_succeeds_with_the_name_from_the_certificate(
        self, tmp_path: Path, ca: FakeCa, server: _TlsServer
    ) -> None:
        config = _config(tmp_path, f"https://localhost:{server.port}", ca.certificate_pem)
        result = probe_channel(config)
        assert result.ok, result.message
        assert "Zertifikat der Plattform gültig" in result.message


class TestCertificateProblemsAreNamedAsSuch:
    """Der Fall vom Dev-Host: Port offen, aber IP statt Name im Endpunkt."""

    def test_ip_endpoint_names_the_certificate_and_not_the_firewall(
        self, tmp_path: Path, ca: FakeCa, server: _TlsServer
    ) -> None:
        config = _config(tmp_path, f"https://127.0.0.1:{server.port}", ca.certificate_pem)
        result = probe_channel(config)
        assert not result.ok
        assert "gilt nicht für '127.0.0.1'" in result.message
        assert "an der Firewall liegt es nicht" in result.message
        assert "46200" not in result.message

    def test_enroll_reports_the_certificate_problem(
        self, tmp_path: Path, ca: FakeCa, server: _TlsServer
    ) -> None:
        config = _config(tmp_path, f"https://127.0.0.1:{server.port}", ca.certificate_pem)
        with pytest.raises(EnrollmentFailedError) as err:
            enroll(config, token="einmal", agent_version="test")
        message = str(err.value)
        assert "gilt nicht für '127.0.0.1'" in message
        assert "TCP 46200 ausgehend offen" not in message
        # Nichts angelegt ausser dem leeren Zustandsverzeichnis.
        assert not config.cert_path.exists()
        assert not config.secrets_path.exists()

    def test_unknown_issuer_points_at_the_ca_bundle(
        self, tmp_path: Path, server: _TlsServer
    ) -> None:
        other = FakeCa()
        config = _config(tmp_path, f"https://localhost:{server.port}", other.certificate_pem)
        result = probe_channel(config)
        assert not result.ok
        assert "ca_bundle" in result.message
        assert str(config.ca_bundle) in result.message


class TestNetworkProblemsAreNamedAsSuch:
    def test_closed_port(self, tmp_path: Path, ca: FakeCa) -> None:
        # 127.0.0.1 statt localhost und die Frist des Produktivcodes: Windows
        # weist einen geschlossenen Port nicht sofort ab, sondern wiederholt
        # den Aufbau rund zwei Sekunden lang — je Adresse, und localhost hat
        # zwei (::1, 127.0.0.1). Mit zwei Sekunden Frist kam dort „keine
        # Antwort" heraus, obwohl der Port abgewiesen hätte.
        config = _config(tmp_path, f"https://127.0.0.1:{_free_port()}", ca.certificate_pem)
        result = probe_channel(config)
        assert not result.ok
        assert "abgewiesen" in result.message
        assert "Zertifikat" not in result.message

    def test_unresolvable_name(self, tmp_path: Path, ca: FakeCa) -> None:
        config = _config(tmp_path, "https://gibts-nicht.invalid:46200", ca.certificate_pem)
        result = probe_channel(config, timeout=2.0)
        assert not result.ok
        assert "nicht auflösen" in result.message

    def test_enroll_against_a_closed_port_names_the_port(self, tmp_path: Path, ca: FakeCa) -> None:
        port = _free_port()
        config = _config(tmp_path, f"https://localhost:{port}", ca.certificate_pem)
        with pytest.raises(EnrollmentFailedError) as err:
            enroll(config, token="einmal", agent_version="test")
        assert f"localhost:{port} abgewiesen" in str(err.value)

    def test_timeout_names_the_port(self, tmp_path: Path, ca: FakeCa) -> None:
        config = _config(tmp_path, "https://connect.magister.test:46200", ca.certificate_pem)
        message = explain_transport_error(TimeoutError("timed out"), config)
        assert "ausgehenden Port 46200" in message

    def test_probe_is_skipped_behind_a_proxy(self, tmp_path: Path, ca: FakeCa) -> None:
        config = _config(
            tmp_path,
            "https://connect.magister.test:46200",
            ca.certificate_pem,
            proxy="http://proxy.local:3128",
        )
        result = probe_channel(config)
        assert result.ok
        assert "Proxy" in result.message


class TestIpHint:
    @pytest.mark.parametrize("endpoint", ["https://172.25.12.10:46200", "https://[::1]:46200"])
    def test_ip_literals_get_a_hint(self, endpoint: str) -> None:
        hint = ip_endpoint_hint(endpoint)
        assert hint is not None
        assert "Namen" in hint

    def test_names_get_none(self) -> None:
        assert ip_endpoint_hint("https://connect.magister.ch:46200") is None
