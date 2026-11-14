"""CA-Attrappe, die einen CSR wie die Plattform signiert.

``FakeCa`` und nicht ``TestCa``: pytest versucht sonst, die Klasse als
Testsammlung zu behandeln.

Die Zertifikate halten RFC 5280 ein: die CA mit ``basicConstraints`` (kritisch),
``keyUsage`` und Subject Key Identifier, jedes ausgestellte Zertifikat mit
Authority Key Identifier auf diese CA. Ab Python 3.13 setzt
``ssl.create_default_context()`` ``VERIFY_X509_STRICT``, und OpenSSL lehnt eine
Kette ohne diese Erweiterungen ab ("Missing Authority Key Identifier") — der
Agent prüft also genau so streng, und eine schlampige Test-CA liesse jeden
TLS-Test scheitern, bevor er bei seiner eigentlichen Frage ankommt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.types import CertificatePublicKeyTypes
from cryptography.x509.oid import NameOID

_CA_KEY_USAGE = x509.KeyUsage(
    digital_signature=False,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=True,
    crl_sign=True,
    encipher_only=False,
    decipher_only=False,
)


@dataclass(frozen=True, slots=True)
class Issued:
    pem: str
    spki: str


class FakeCa:
    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP384R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Magister Connector Issuing CA")])
        now = dt.datetime.now(dt.UTC)
        self._key_id = x509.SubjectKeyIdentifier.from_public_key(self._key.public_key())
        self.certificate = self._identified(
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self._key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(_CA_KEY_USAGE, critical=True),
            self._key.public_key(),
        ).sign(self._key, hashes.SHA384())

    def _identified(
        self, builder: x509.CertificateBuilder, public_key: CertificatePublicKeyTypes
    ) -> x509.CertificateBuilder:
        """Subject Key Identifier des Zertifikats und Authority Key Identifier dieser CA."""
        return builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
        ).add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(self._key_id),
            critical=False,
        )

    def issue(self, csr_pem: str) -> Issued:
        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        now = dt.datetime.now(dt.UTC)
        cert = self._identified(
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "connector-agent:dc01")])
            )
            .issuer_name(self.certificate.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([x509.ObjectIdentifier("1.3.6.1.5.5.7.3.2")]),
                critical=True,
            ),
            csr.public_key(),
        ).sign(self._key, hashes.SHA384())
        der = csr.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return Issued(
            pem=cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            spki=hashlib.sha256(der).hexdigest(),
        )

    def issue_server(self, dns_name: str) -> tuple[str, str]:
        """Server-Zertifikat für ``dns_name``. Rückgabe: (Zertifikat-PEM, Schlüssel-PEM).

        Mit SubjectAltName, wie die Plattform es hat: ohne SAN prüft keine
        aktuelle TLS-Bibliothek den Namen mehr, und ein Test gegen ein solches
        Zertifikat sähe nie den Fehler, um den es geht.
        """
        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.UTC)
        cert = self._identified(
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_name)]))
            .issuer_name(self.certificate.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
            .add_extension(
                x509.ExtendedKeyUsage([x509.ObjectIdentifier("1.3.6.1.5.5.7.3.1")]),
                critical=False,
            ),
            key.public_key(),
        ).sign(self._key, hashes.SHA384())
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), key_pem

    @property
    def certificate_pem(self) -> str:
        return self.certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def write_enrolled_state(state_dir: Path, ca: FakeCa) -> str:
    """Ein angemeldetes Zustandsverzeichnis anlegen.

    Echte Dateien, kein Platzhalter: ``Runner.build_client`` baut daraus einen
    ``ssl.SSLContext``, und der lädt das Zertifikat wirklich. Ein Test mit
    Attrappen-Dateien würde genau den Pfad überspringen, an dem sich httpx
    0.28 anders verhält als seine eigene Dokumentation.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent")]))
        .sign(key, hashes.SHA256())
    )
    issued = ca.issue(csr.public_bytes(serialization.Encoding.PEM).decode("ascii"))
    key_path = state_dir / "agent-key.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    (state_dir / "agent.pem").write_text(issued.pem, encoding="utf-8")
    (state_dir / "ca.pem").write_bytes(ca.certificate.public_bytes(serialization.Encoding.PEM))
    return issued.spki
