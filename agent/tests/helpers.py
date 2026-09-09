"""CA-Attrappe, die einen CSR wie die Plattform signiert.

``FakeCa`` und nicht ``TestCa``: pytest versucht sonst, die Klasse als
Testsammlung zu behandeln.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass(frozen=True, slots=True)
class Issued:
    pem: str
    spki: str


class FakeCa:
    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP384R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Magister Connector Issuing CA")])
        now = dt.datetime.now(dt.UTC)
        self.certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self._key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(self._key, hashes.SHA384())
        )

    def issue(self, csr_pem: str) -> Issued:
        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        now = dt.datetime.now(dt.UTC)
        cert = (
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
            )
            .sign(self._key, hashes.SHA384())
        )
        der = csr.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return Issued(
            pem=cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            spki=hashlib.sha256(der).hexdigest(),
        )


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
