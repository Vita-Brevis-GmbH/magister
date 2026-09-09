"""Anmeldung des Agenten (ADR-0014).

Der Ablauf, und warum er so ist:

1. Der Agent erzeugt sein Schlüsselpaar **lokal**. Es verlässt den Server nie —
   auch nicht verschlüsselt, auch nicht zur Plattform. Damit kann selbst Vita
   Brevis sich nicht als dieser Agent ausgeben.
2. Er baut einen CSR. Ein CSR trägt den öffentlichen Schlüssel und eine
   Selbstsignatur, sonst nichts.
3. Er löst das Einmal-Token gegen Zertifikat, API-Key und HMAC-Schlüssel ein.
   Das Token ist damit verbraucht.
4. Er schreibt alles mit ``0600`` weg und meldet den Fingerprint.

Der Fingerprint gehört in die Abnahme: die Konsole zeigt ihn nach der
Anmeldung, und wer beim Kunden installiert hat, vergleicht. Weichen sie ab, hat
sich jemand anders mit dem Token angemeldet — das ist der Grund, warum das
Token kurz lebt und nur einmal gilt.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, cast

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from connector_agent.config import (
    AgentConfig,
    AgentSecrets,
    ensure_state_dir,
    save_secrets,
    write_secret_file,
)
from connector_agent.tls import build_context

logger = logging.getLogger(__name__)

#: Kurve für das Schlüsselpaar des Agenten. P-256 reicht, ist überall
#: unterstützt und schnell auf einem Windows-Server ohne Beschleunigung.
CURVE = ec.SECP256R1


class EnrollmentFailedError(RuntimeError):
    """Die Anmeldung ist gescheitert. Der Zustand bleibt unberührt."""


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    agent_id: str
    spki_sha256: str
    certificate_not_after: str


def generate_key_and_csr(common_name: str) -> tuple[bytes, str]:
    """Schlüsselpaar und CSR erzeugen. Rückgabe: (Schlüssel-PEM, CSR-PEM).

    Der Subject im CSR ist bewusst schlicht: die Plattform ersetzt ihn ohnehin
    (sie bestimmt, wie der Agent heisst — sonst könnte der Antragsteller sich
    ``connector-agent:console`` nennen). Er steht nur drin, weil ein CSR ohne
    Subject bei manchen Werkzeugen Ärger macht.
    """
    key = CURVE and ec.generate_private_key(CURVE())
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return key_pem, csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def spki_fingerprint_from_certificate(pem: str) -> str:
    cert = x509.load_pem_x509_certificate(pem.encode("utf-8"))
    der = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()


def enroll(
    config: AgentConfig,
    *,
    token: str,
    agent_version: str,
    common_name: str = "magister-connector-agent",
    transport: httpx.BaseTransport | None = None,
) -> EnrollmentResult:
    ensure_state_dir(config.state_dir)
    if config.cert_path.exists() or config.secrets_path.exists():
        # Nicht überschreiben: ein zweiter Anmeldelauf über einen bestehenden
        # Agenten würde den alten stumm aussperren, und der Fingerprint in der
        # Konsole zeigte plötzlich auf ein anderes Schlüsselpaar.
        raise EnrollmentFailedError(
            f"In {config.state_dir} liegt bereits eine Anmeldung. Zum Neuanmelden "
            "erst den Agenten in der Konsole widerrufen und das Verzeichnis leeren."
        )
    key_pem, csr_pem = generate_key_and_csr(common_name)

    # Ohne Client-Zertifikat: der Agent hat noch keines, das ist der Zweck
    # dieses Aufrufs. Die Serverprüfung gilt trotzdem — sonst könnte ein
    # Angreifer im Netz die Plattform spielen und das Einmal-Token einsammeln.
    context = build_context(ca_bundle=config.ca_bundle)
    try:
        with httpx.Client(
            timeout=30.0,
            verify=context,
            trust_env=False,
            proxy=config.proxy,
            transport=transport,
        ) as client:
            resp = client.post(
                f"{config.endpoint}/connector/enroll",
                json={"token": token, "csr_pem": csr_pem, "agent_version": agent_version},
            )
    except httpx.HTTPError as exc:
        raise EnrollmentFailedError(
            f"Die Plattform ist nicht erreichbar: {exc}. Ist TCP 46200 ausgehend offen?"
        ) from exc
    if resp.status_code == 401:
        raise EnrollmentFailedError(
            "Das Einmal-Token wurde abgelehnt: unbekannt, abgelaufen oder schon "
            "eingelöst. Ein neues in der Konsole ausstellen."
        )
    if resp.status_code != 201:
        detail = _detail(resp)
        raise EnrollmentFailedError(f"Anmeldung abgelehnt (HTTP {resp.status_code}): {detail}")

    body = resp.json()
    certificate_pem = str(body["certificate_pem"])
    local = spki_fingerprint_from_certificate(certificate_pem)
    remote = str(body["spki_sha256"])
    if local != remote:
        # Das Zertifikat gehört nicht zu unserem Schlüssel. Entweder ein Fehler
        # der Plattform oder jemand dazwischen — in beiden Fällen wird nichts
        # gespeichert.
        raise EnrollmentFailedError(
            "Das ausgestellte Zertifikat passt nicht zum lokal erzeugten Schlüssel "
            f"(erwartet {local}, erhalten {remote}). Es wird nichts gespeichert."
        )

    write_secret_file(config.key_path, key_pem.decode("ascii"))
    config.cert_path.write_text(certificate_pem, encoding="utf-8")
    save_secrets(
        config,
        AgentSecrets(
            agent_id=str(body["agent_id"]),
            api_key=str(body["api_key"]),
            result_hmac_key=str(body["result_hmac_key"]),
            spki_sha256=remote,
        ),
    )
    logger.info("Agent angemeldet. SPKI-Fingerprint: %s", remote)
    logger.info("Diesen Fingerprint mit der Anzeige in der Konsole vergleichen.")
    return EnrollmentResult(
        agent_id=str(body["agent_id"]),
        spki_sha256=remote,
        certificate_not_after=str(body["certificate_not_after"]),
    )


def _detail(resp: httpx.Response) -> str:
    try:
        payload: object = resp.json()
    except (json.JSONDecodeError, ValueError):
        return resp.text[:200]
    if not isinstance(payload, dict):
        return resp.text[:200]
    detail: object = cast(dict[str, Any], payload).get("detail")
    return str(detail) if detail else resp.text[:200]


__all__ = [
    "EnrollmentFailedError",
    "EnrollmentResult",
    "enroll",
    "generate_key_and_csr",
    "spki_fingerprint_from_certificate",
]
