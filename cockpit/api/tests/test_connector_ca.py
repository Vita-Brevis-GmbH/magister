"""Agent-Zertifikate ausstellen (ADR-0014).

Gegen eine eigens gebaute Test-CA, nicht gegen Zusicherungen: die Zeremonie
der echten Plattform-CA steht noch aus, der Code-Pfad ist derselbe.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtensionOID, NameOID

from cockpit_api.services.connector_ca import (
    AGENT_CERT_DAYS,
    CertificateIssueError,
    ConnectorCa,
    spki_fingerprint,
    spki_fingerprint_from_certificate,
)


@pytest.fixture
def ca(tmp_path: Path) -> ConnectorCa:
    """Ein Intermediate, wie die Zeremonie es ausstellen wird."""
    key = ec.generate_private_key(ec.SECP384R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CH"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Vita Brevis GmbH"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Magister Connector Issuing CA"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA384())
    )
    cert_path = tmp_path / "connector-int.pem"
    key_path = tmp_path / "connector-int-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ConnectorCa(str(cert_path), str(key_path))


def _csr(key: object | None = None, *, common_name: str = "irgendwas") -> tuple[str, object]:
    """Ein CSR, wie der Agent ihn erzeugt. Der Schlüssel bleibt beim Aufrufer."""
    private = key or ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(private, hashes.SHA256())  # type: ignore[arg-type]
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii"), private


class TestIssuance:
    def test_a_valid_csr_gets_a_client_certificate(self, ca: ConnectorCa) -> None:
        csr_pem, _key = _csr()
        issued = ca.issue(csr_pem, tenant_slug="musterstadt", agent_name="dc01")

        cert = x509.load_pem_x509_certificate(issued.certificate_pem.encode())
        # Nur Client-Authentisierung: damit lässt sich kein Server aufziehen,
        # der sich als Plattform ausgibt.
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
        assert list(eku) == [x509.ObjectIdentifier("1.3.6.1.5.5.7.3.2")]  # type: ignore[call-overload]
        basic = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
        assert basic.ca is False  # type: ignore[attr-defined]
        usage = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        assert usage.digital_signature is True  # type: ignore[attr-defined]
        assert usage.key_cert_sign is False  # type: ignore[attr-defined]

    def test_the_subject_comes_from_us_not_from_the_csr(self, ca: ConnectorCa) -> None:
        """Sonst bestimmte der Antragsteller, wie er heisst.

        Ein CSR mit ``CN=magister-console`` darf kein Zertifikat ergeben, das
        so heisst — der Subject wird aus der Agent-Zeile gesetzt.
        """
        csr_pem, _ = _csr(common_name="magister-console")
        issued = ca.issue(csr_pem, tenant_slug="musterstadt", agent_name="dc01")
        cert = x509.load_pem_x509_certificate(issued.certificate_pem.encode())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == "connector-agent:dc01"
        ou = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)[0].value
        assert ou == "tenant:musterstadt"

    def test_the_fingerprint_is_over_the_public_key(self, ca: ConnectorCa) -> None:
        """Damit eine Erneuerung mit demselben Schlüssel die Bindung nicht löst.

        Ein Fingerprint über das Zertifikat müsste bei jeder Erneuerung
        nachgezogen werden — und jede Nachzieh-Mechanik ist eine Stelle, an der
        die Bindung gelockert wird.
        """
        csr_pem, key = _csr()
        first = ca.issue(csr_pem, tenant_slug="a", agent_name="dc01")
        second = ca.issue(csr_pem, tenant_slug="a", agent_name="dc01")
        assert first.serial_hex != second.serial_hex, "zwei Zertifikate"
        assert first.spki_sha256 == second.spki_sha256, "aber ein Schlüssel"
        assert first.spki_sha256 == spki_fingerprint(key.public_key())  # type: ignore[attr-defined]

    def test_the_fingerprint_round_trips_through_pem(self, ca: ConnectorCa) -> None:
        # Der Weg des Anfragepfads: der Proxy leitet das Zertifikat weiter, die
        # Anwendung rechnet den Fingerprint nach.
        csr_pem, _ = _csr()
        issued = ca.issue(csr_pem, tenant_slug="a", agent_name="dc01")
        assert spki_fingerprint_from_certificate(issued.certificate_pem) == issued.spki_sha256

    def test_the_lifetime_is_short(self, ca: ConnectorCa) -> None:
        csr_pem, _ = _csr()
        issued = ca.issue(csr_pem, tenant_slug="a", agent_name="dc01")
        days = (issued.not_after - dt.datetime.now(dt.UTC)).days
        assert AGENT_CERT_DAYS - 1 <= days <= AGENT_CERT_DAYS

    def test_it_chains_to_the_intermediate(self, ca: ConnectorCa, tmp_path: Path) -> None:
        csr_pem, _ = _csr()
        issued = ca.issue(csr_pem, tenant_slug="a", agent_name="dc01")
        cert = x509.load_pem_x509_certificate(issued.certificate_pem.encode())
        intermediate = x509.load_pem_x509_certificate((tmp_path / "connector-int.pem").read_bytes())
        assert cert.issuer == intermediate.subject
        # Signatur wirklich nachrechnen, nicht nur die Namen vergleichen.
        intermediate.public_key().verify(  # type: ignore[call-arg]
            cert.signature,
            cert.tbs_certificate_bytes,
            ec.ECDSA(cert.signature_hash_algorithm),  # type: ignore[arg-type]
        )


class TestRefusals:
    def test_garbage_is_refused(self, ca: ConnectorCa) -> None:
        with pytest.raises(CertificateIssueError, match="nicht lesbar"):
            ca.issue("kein CSR", tenant_slug="a", agent_name="dc01")

    def test_a_short_rsa_key_is_refused(self, ca: ConnectorCa) -> None:
        """Ablehnung, nicht Warnung: ein zu kurzer Schlüssel im Feld lässt
        sich später nicht mehr einsammeln."""
        weak = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr_pem, _ = _csr(weak)
        with pytest.raises(CertificateIssueError, match="zu kurz"):
            ca.issue(csr_pem, tenant_slug="a", agent_name="dc01")

    def test_a_strong_rsa_key_is_accepted(self, ca: ConnectorCa) -> None:
        strong = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        csr_pem, _ = _csr(strong)
        assert ca.issue(csr_pem, tenant_slug="a", agent_name="dc01").certificate_pem

    def test_a_tampered_csr_is_refused(self, ca: ConnectorCa) -> None:
        """Ein CSR mit fremdem öffentlichem Schlüssel und ungültiger Signatur.

        Ohne diese Prüfung könnte jemand den Schlüssel eines anderen Agenten
        einreichen. Er könnte das Zertifikat nie benutzen — aber der
        Fingerprint des Opfers wäre an seine Agent-Zeile gebunden, und damit
        wäre der echte Agent ausgesperrt.
        """
        csr_pem, _ = _csr()
        lines = csr_pem.strip().splitlines()
        # Ein Zeichen im base64-Körper drehen.
        body = lines[2]
        flipped = ("B" if body[5] != "B" else "C").join([body[:5], body[6:]])
        lines[2] = flipped
        with pytest.raises(CertificateIssueError):
            ca.issue("\n".join(lines) + "\n", tenant_slug="a", agent_name="dc01")

    def test_a_missing_ca_file_is_a_clear_error(self, tmp_path: Path) -> None:
        broken = ConnectorCa(str(tmp_path / "fehlt.pem"), str(tmp_path / "fehlt-key.pem"))
        csr_pem, _ = _csr()
        with pytest.raises(CertificateIssueError, match="fehlt"):
            broken.issue(csr_pem, tenant_slug="a", agent_name="dc01")

    def test_unconfigured_ca_names_the_variables(self) -> None:
        with pytest.raises(CertificateIssueError, match="COCKPIT_CONNECTOR_CA_CERT"):
            ConnectorCa.from_settings("", "")
