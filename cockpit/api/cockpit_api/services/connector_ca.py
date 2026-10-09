"""Zertifikate für Connector-Agenten ausstellen (ADR-0014).

Der Agent erzeugt sein Schlüsselpaar **lokal** und schickt nur einen CSR. Die
Plattform signiert ihn mit dem Intermediate Connector und speichert den
SPKI-Fingerprint des öffentlichen Schlüssels. Der private Schlüssel des Agenten
erreicht die Plattform nie — auch nicht versehentlich, denn ein CSR enthält ihn
nicht.

Warum der Fingerprint über den **öffentlichen Schlüssel** (SubjectPublicKeyInfo)
und nicht über das Zertifikat: eine Erneuerung mit demselben Schlüsselpaar
ändert das Zertifikat, aber nicht den Schlüssel. Ein Fingerprint über das
Zertifikat müsste bei jeder Erneuerung nachgezogen werden, und jede solche
Nachzieh-Mechanik ist eine Stelle, an der die Bindung gelockert wird.

Was hier absichtlich **nicht** passiert: der CSR bestimmt nicht den Subject.
Wer einen CSR schickt, könnte sonst `CN=magister-console` hineinschreiben. Der
Subject wird aus der Agent-Zeile gesetzt; aus dem CSR kommt ausschliesslich der
öffentliche Schlüssel.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

#: Laufzeit eines Agent-Zertifikats. Kurz, weil die Erneuerung automatisch
#: läuft — ein langlebiges Zertifikat ist nur dann bequem, wenn die Erneuerung
#: weh tut.
AGENT_CERT_DAYS = 90

#: Kleinste akzeptierte RSA-Schlüssellänge. Kleiner heisst Ablehnung, nicht
#: Warnung: ein zu kurzer Schlüssel im Feld lässt sich später nicht mehr
#: einsammeln.
MIN_RSA_BITS = 3072


class CertificateIssueError(RuntimeError):
    """Der CSR ist unbrauchbar oder die CA nicht einsatzbereit."""


@dataclass(frozen=True, slots=True)
class IssuedCertificate:
    certificate_pem: str
    serial_hex: str
    not_after: dt.datetime
    spki_sha256: str


def spki_fingerprint(public_key: object) -> str:
    """SHA-256 über den DER-kodierten öffentlichen Schlüssel, hex."""
    der = public_key.public_bytes(  # type: ignore[attr-defined]
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def spki_fingerprint_from_der_base64(value: str) -> str:
    """Fingerprint aus einem base64-kodierten DER-Zertifikat.

    Das ist der Weg des Anfragepfads. Warum base64-DER und nicht PEM: ein PEM
    enthält Zeilenumbrüche, und Gos ``net/http`` weist einen Header-Wert mit
    Zeilenumbruch ab — Caddy hätte jede Agent-Anfrage mit 502 beantwortet.
    Nachgemessen, nicht überlegt: der erste Entwurf benutzte
    ``{http.request.tls.client.certificate_pem}`` und scheiterte genau daran.
    Der Platzhalter im Caddyfile ist deshalb
    ``{http.request.tls.client.certificate_der_base64}``.
    """
    cleaned = "".join(value.split())
    try:
        der = base64.b64decode(cleaned, validate=True)
    except Exception as exc:
        raise CertificateIssueError(f"Zertifikat ist kein gültiges base64: {exc}") from exc
    try:
        cert = x509.load_der_x509_certificate(der)
    except Exception as exc:
        # Breit gefangen: siehe unten, ein beschädigtes DER liefert nicht nur
        # ValueError.
        raise CertificateIssueError(f"Zertifikat ist nicht lesbar: {exc}") from exc
    return spki_fingerprint(cert.public_key())


def spki_fingerprint_from_certificate(pem: str | bytes) -> str:
    """Fingerprint aus einem Zertifikat im PEM-Format.

    Nur für Werkzeuge und Tests; der Anfragepfad nimmt
    ``spki_fingerprint_from_der_base64``.
    """
    raw = pem.encode("utf-8") if isinstance(pem, str) else pem
    try:
        cert = x509.load_pem_x509_certificate(raw)
    except Exception as exc:
        # Breit gefangen mit Absicht: ein beschädigtes DER liefert nicht nur
        # ValueError, sondern je nach Schadstelle auch UnsupportedAlgorithm.
        # Die Eingabe kommt von aussen — sie darf einen klaren Fehler ergeben,
        # nie eine unbehandelte Ausnahme (also einen 500er).
        raise CertificateIssueError(f"Zertifikat ist nicht lesbar: {exc}") from exc
    return spki_fingerprint(cert.public_key())


def _check_public_key(public_key: object) -> None:
    if isinstance(public_key, rsa.RSAPublicKey):
        if public_key.key_size < MIN_RSA_BITS:
            raise CertificateIssueError(
                f"RSA-Schlüssel mit {public_key.key_size} Bit ist zu kurz; "
                f"mindestens {MIN_RSA_BITS} Bit."
            )
        return
    if isinstance(public_key, ec.EllipticCurvePublicKey | ed25519.Ed25519PublicKey):
        return
    raise CertificateIssueError(
        "Nicht unterstützter Schlüsseltyp im CSR. Erlaubt sind ECDSA, Ed25519 "
        f"und RSA ab {MIN_RSA_BITS} Bit."
    )


class ConnectorCa:
    """Das Intermediate Connector auf dem Plattform-Server."""

    def __init__(self, cert_path: str, key_path: str, key_password: bytes | None = None) -> None:
        self._cert_path = Path(cert_path)
        self._key_path = Path(key_path)
        self._key_password = key_password

    @classmethod
    def from_settings(cls, cert_path: str, key_path: str) -> ConnectorCa:
        if not cert_path or not key_path:
            raise CertificateIssueError(
                "COCKPIT_CONNECTOR_CA_CERT und COCKPIT_CONNECTOR_CA_KEY sind nicht "
                "gesetzt. Ohne das Intermediate Connector kann kein Agent "
                "angemeldet werden — siehe docs/runbooks/platform-ca.md."
            )
        return cls(cert_path, key_path)

    def _load(self) -> tuple[x509.Certificate, object]:
        for path in (self._cert_path, self._key_path):
            if not path.is_file():
                raise CertificateIssueError(f"CA-Datei {path} fehlt.")
        cert = x509.load_pem_x509_certificate(self._cert_path.read_bytes())
        key = serialization.load_pem_private_key(
            self._key_path.read_bytes(), password=self._key_password
        )
        return cert, key

    def issue(self, csr_pem: str, *, tenant_slug: str, agent_name: str) -> IssuedCertificate:
        try:
            csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
            signature_ok = csr.is_signature_valid
        except Exception as exc:
            # Siehe spki_fingerprint_from_certificate: ein beschädigtes DER
            # kann UnsupportedAlgorithm werfen, und die Signaturprüfung selbst
            # kann an einem unlesbaren Algorithmus scheitern. Beides ist
            # dasselbe Ergebnis: kein Zertifikat.
            raise CertificateIssueError(f"CSR ist nicht lesbar: {exc}") from exc
        if not signature_ok:
            # Ohne diese Prüfung könnte jemand einen fremden öffentlichen
            # Schlüssel einreichen und sich ein Zertifikat darauf ausstellen
            # lassen, das er nie benutzen kann — aber der Fingerprint des
            # Opfers wäre dann an seine Agent-Zeile gebunden.
            raise CertificateIssueError("CSR-Selbstsignatur ist ungültig.")

        public_key = csr.public_key()
        _check_public_key(public_key)

        ca_cert, ca_key = self._load()
        now = dt.datetime.now(dt.UTC)
        # Der Subject kommt aus unserer Zeile, NICHT aus dem CSR: sonst
        # bestimmte der Antragsteller, wie er heisst.
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "CH"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Vita Brevis GmbH"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f"tenant:{tenant_slug}"),
                x509.NameAttribute(NameOID.COMMON_NAME, f"connector-agent:{agent_name}"),
            ]
        )
        not_after = now + dt.timedelta(days=AGENT_CERT_DAYS)
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(public_key)  # type: ignore[arg-type]
            .serial_number(x509.random_serial_number())
            # Eine Minute Rückdatierung gegen Uhrenversatz beim Agenten.
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            # Nur Client-Authentisierung: mit diesem Zertifikat lässt sich kein
            # Server aufziehen, der sich als Plattform ausgibt.
            .add_extension(
                x509.ExtendedKeyUsage([x509.ObjectIdentifier("1.3.6.1.5.5.7.3.2")]),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(public_key),  # type: ignore[arg-type]
                critical=False,
            )
        )
        certificate = builder.sign(private_key=ca_key, algorithm=hashes.SHA384())  # type: ignore[arg-type]
        pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
        logger.info(
            "Agent-Zertifikat ausgestellt für Kunde %s, Agent %s, Seriennummer %x",
            tenant_slug,
            agent_name,
            certificate.serial_number,
        )
        return IssuedCertificate(
            certificate_pem=pem,
            serial_hex=f"{certificate.serial_number:x}",
            not_after=not_after,
            spki_sha256=spki_fingerprint(public_key),
        )
