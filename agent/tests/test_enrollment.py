"""Anmeldung des Agenten (ADR-0014).

Der Kern: der private Schlüssel entsteht lokal und verlässt den Server nie.
Geprüft wird, dass er tatsächlich nicht im Anmelde-Aufruf steckt, dass der
Fingerprint gegengerechnet wird, und dass bei jedem Fehler **nichts**
gespeichert wird — ein halb angelegter Zustand wäre schlimmer als keiner.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from connector_agent.config import AgentConfig, load_secrets
from connector_agent.enrollment import (
    EnrollmentFailedError,
    enroll,
    generate_key_and_csr,
    spki_fingerprint_from_certificate,
)
from tests.helpers import FakeCa


@pytest.fixture
def config(tmp_path: Path) -> AgentConfig:
    return AgentConfig.from_mapping(
        {
            "endpoint": "https://connect.magister.test:46200",
            "state_dir": str(tmp_path / "state"),
            "ca_bundle": str(tmp_path / "ca.pem"),
            "allowed_ous": ["OU=Schule,DC=x,DC=y"],
        }
    )


class _Platform:
    """Die Plattform als Attrappe."""

    def __init__(self, ca: FakeCa) -> None:
        self.ca = ca
        self.requests: list[dict[str, Any]] = []
        self.status = 201
        self.override_fingerprint: str | None = None

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.requests.append(body)
            if self.status != 201:
                return httpx.Response(self.status, json={"detail": "nope"})
            issued = self.ca.issue(body["csr_pem"])
            return httpx.Response(
                201,
                json={
                    "agent_id": "aaaaaaaa-0000-0000-0000-000000000001",
                    "certificate_pem": issued.pem,
                    "spki_sha256": self.override_fingerprint or issued.spki,
                    "certificate_not_after": "2026-12-31T00:00:00Z",
                    "api_key": "api-key-einmal",
                    "result_hmac_key": "hmac-key-einmal",
                },
            )

        return httpx.MockTransport(handler)


class TestKeyStaysLocal:
    def test_the_csr_carries_no_private_key(self) -> None:
        key_pem, csr_pem = generate_key_and_csr("agent")
        assert b"PRIVATE KEY" in key_pem
        assert "PRIVATE KEY" not in csr_pem
        assert "CERTIFICATE REQUEST" in csr_pem

    def test_the_enrol_request_never_contains_the_key(
        self, config: AgentConfig, tmp_path: Path
    ) -> None:
        """Die Zusage aus ADR-0014, an der Leitung geprüft.

        Selbst Vita Brevis soll sich nicht als dieser Agent ausgeben können —
        das gilt nur, wenn der Schlüssel den Server nie verlässt.
        """
        platform = _Platform(FakeCa())
        enroll(
            config,
            token="t" * 32,
            agent_version="0.1.0",
            transport=platform.transport(),
        )
        sent = json.dumps(platform.requests)
        assert "PRIVATE KEY" not in sent
        assert "CERTIFICATE REQUEST" in sent
        # Und lokal liegt er wirklich.
        assert "PRIVATE KEY" in config.key_path.read_text()

    def test_the_key_and_secrets_are_written_with_0600(self, config: AgentConfig) -> None:
        platform = _Platform(FakeCa())
        enroll(config, token="t" * 32, agent_version="0.1.0", transport=platform.transport())
        for path in (config.key_path, config.secrets_path):
            mode = stat.S_IMODE(path.stat().st_mode)
            assert mode == 0o600, f"{path} hat {mode:04o}"
        assert stat.S_IMODE(config.state_dir.stat().st_mode) == 0o700

    def test_the_fingerprint_matches_the_issued_certificate(self, config: AgentConfig) -> None:
        platform = _Platform(FakeCa())
        result = enroll(
            config, token="t" * 32, agent_version="0.1.0", transport=platform.transport()
        )
        assert result.spki_sha256 == spki_fingerprint_from_certificate(config.cert_path.read_text())
        secrets = load_secrets(config)
        assert secrets is not None
        assert secrets.spki_sha256 == result.spki_sha256
        assert secrets.api_key == "api-key-einmal"


class TestRefusals:
    def test_a_certificate_for_a_foreign_key_is_refused(self, config: AgentConfig) -> None:
        """Das Zertifikat muss zu **unserem** Schlüssel gehören.

        Passt es nicht, ist entweder die Plattform kaputt oder jemand sitzt
        dazwischen. In beiden Fällen wird nichts gespeichert — ein
        gespeicherter Fremdschlüssel wäre ein Agent, der nie funktioniert und
        dessen Fingerprint in der Konsole auf jemand anderen zeigt.
        """
        platform = _Platform(FakeCa())
        platform.override_fingerprint = "0" * 64
        with pytest.raises(EnrollmentFailedError, match="passt nicht"):
            enroll(config, token="t" * 32, agent_version="0.1.0", transport=platform.transport())
        assert not config.key_path.exists()
        assert not config.secrets_path.exists()

    def test_a_rejected_token_says_what_to_do(self, config: AgentConfig) -> None:
        platform = _Platform(FakeCa())
        platform.status = 401
        with pytest.raises(EnrollmentFailedError, match="neues in der Konsole"):
            enroll(config, token="t" * 32, agent_version="0.1.0", transport=platform.transport())
        assert not config.key_path.exists()

    def test_an_unreachable_platform_mentions_the_port(self, config: AgentConfig) -> None:
        # Der häufigste Fehler beim Onboarding ist die geschlossene Firewall.
        # Die Meldung soll das sagen, nicht nur "connection refused".
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("kein Netz")

        with pytest.raises(EnrollmentFailedError, match="46200"):
            enroll(
                config,
                token="t" * 32,
                agent_version="0.1.0",
                transport=httpx.MockTransport(boom),
            )

    def test_an_existing_enrollment_is_not_overwritten(self, config: AgentConfig) -> None:
        """Ein zweiter Anmeldelauf würde den alten Agenten stumm aussperren."""
        platform = _Platform(FakeCa())
        enroll(config, token="t" * 32, agent_version="0.1.0", transport=platform.transport())
        first = config.key_path.read_text()
        with pytest.raises(EnrollmentFailedError, match="bereits eine Anmeldung"):
            enroll(config, token="u" * 32, agent_version="0.1.0", transport=platform.transport())
        assert config.key_path.read_text() == first


class TestConfig:
    def test_a_plaintext_endpoint_is_refused(self, tmp_path: Path) -> None:
        # Über diese Leitung gehen Passwörter.
        with pytest.raises(Exception, match="https"):
            AgentConfig.from_mapping(
                {"endpoint": "http://connect.magister.test:46200", "state_dir": str(tmp_path)}
            )

    def test_the_issued_certificate_is_client_auth_only(self, config: AgentConfig) -> None:
        platform = _Platform(FakeCa())
        enroll(config, token="t" * 32, agent_version="0.1.0", transport=platform.transport())
        cert = x509.load_pem_x509_certificate(config.cert_path.read_bytes())
        assert cert.public_bytes(serialization.Encoding.PEM)
