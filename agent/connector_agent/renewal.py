"""Zertifikatserneuerung des Agenten (ADR-0014).

Das Agentenzertifikat gilt 90 Tage. Ohne Erneuerung wäre der Ablauf ein
Widerruf in der Konsole plus ein neues Einmal-Token plus ein Besuch beim
Kunden — alle drei Monate, je Agent. Das hält niemand durch, und die Folge
wäre nicht ein sauberer Ablauf, sondern stillgelegte Agenten und ein
längeres Zertifikat.

Erneuert wird über den **beglaubigten** Kanal: bestehendes Client-Zertifikat
plus API-Key. Kein Token, kein Mensch.

**Der Fallstrick, um den herum hier alles gebaut ist:** eine Erneuerung
wechselt Schlüssel *und* Zertifikat, und das sind zwei Dateien. Stirbt der
Prozess zwischen den beiden Umbenennungen, liegt ein neuer Schlüssel neben
einem alten Zertifikat — sie passen nicht zusammen, und der TLS-Handshake
scheitert lokal, bevor überhaupt eine Verbindung zustande kommt. Der Agent
wäre stumm, und im Protokoll stünde eine OpenSSL-Meldung, die niemand mit
„Erneuerung" verbindet.

Dagegen zwei Dinge:

1. **Das alte Paar bleibt als ``.prev`` liegen.** Passt das aktive Paar nicht
   zusammen, wird es beim Start daraus wiederhergestellt. Das alte Zertifikat
   gilt zu diesem Zeitpunkt noch (erneuert wird 30 Tage vor Ablauf), und die
   Plattform akzeptiert den alten Fingerprint im Übergangsfenster — der Agent
   läuft also weiter und versucht die Erneuerung erneut.
2. **Der Schlüssel wird zuletzt getauscht.** Ein neues Zertifikat zu einem
   alten Schlüssel ist derselbe Fehler, aber in der Reihenfolge lässt sich
   nur einer von beiden zuerst schreiben — und diese Richtung ist die, in der
   das *alte* Paar länger vollständig bleibt.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from connector_agent.config import AgentConfig, AgentSecrets, save_secrets, write_secret_file
from connector_agent.enrollment import (
    generate_key_and_csr,
    spki_fingerprint_from_certificate,
)
from connector_agent.tls import build_context

logger = logging.getLogger(__name__)

#: Wie viele Tage vor Ablauf erneuert wird.
#:
#: 30 von 90 ist reichlich, und das ist Absicht: scheitert die Erneuerung,
#: bleibt ein Monat, in dem sie stündlich erneut versucht wird und in dem ein
#: Mensch eingreifen kann. Bei 7 Tagen wäre eine Woche Betriebsferien beim
#: Kunden genug, um den Agenten stillzulegen.
RENEW_BEFORE_DAYS = 30

#: Mindestabstand zwischen zwei Versuchen. Scheitert die Erneuerung, soll der
#: Agent nicht bei jedem Long-Poll erneut anklopfen — das wären 3400 Versuche
#: pro Tag gegen einen Endpunkt, der eine CA bemüht.
RETRY_AFTER = dt.timedelta(hours=1)

#: Endung der Sicherheitskopie des alten Paares.
PREV_SUFFIX = ".prev"


class RenewalError(RuntimeError):
    """Die Erneuerung ist gescheitert. Das bestehende Paar bleibt in Kraft."""


@dataclass(frozen=True, slots=True)
class RenewalResult:
    spki_sha256: str
    certificate_not_after: dt.datetime


def certificate_not_after(cert_path: Path) -> dt.datetime:
    """Ablaufzeitpunkt des aktiven Zertifikats, zeitzonenbewusst."""
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RenewalError(f"Zertifikat {cert_path} ist nicht lesbar: {exc}") from exc
    # not_valid_after_utc gibt es seit cryptography 42; die alte Eigenschaft
    # ist zeitzonenlos und führt zu Vergleichen, die um Stunden falsch liegen.
    return cert.not_valid_after_utc


def days_until_expiry(cert_path: Path, *, now: dt.datetime | None = None) -> float:
    moment = now or dt.datetime.now(dt.UTC)
    return (certificate_not_after(cert_path) - moment).total_seconds() / 86400.0


def is_due(
    cert_path: Path,
    *,
    now: dt.datetime | None = None,
    before_days: int = RENEW_BEFORE_DAYS,
) -> bool:
    """Ist eine Erneuerung fällig?

    Ein unlesbares Zertifikat gilt als fällig: dann ist etwas kaputt, und ein
    Versuch ist besser als Stillstand. Scheitert er, sagt das Protokoll warum.
    """
    try:
        return days_until_expiry(cert_path, now=now) <= before_days
    except RenewalError:
        return True


def pair_matches(cert_path: Path, key_path: Path) -> bool:
    """Gehören Zertifikat und Schlüssel zusammen?

    Die Frage, die nach einem Absturz mitten in der Erneuerung entscheidet.
    Verglichen werden die öffentlichen Schlüssel — nicht die Dateizeiten, die
    nach einem ``os.replace`` nichts aussagen.
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        return False
    try:
        return cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ) == key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    except Exception:  # pragma: no cover - unpassende Schlüsseltypen
        return False


def recover_if_broken(config: AgentConfig) -> bool:
    """Nach einem Absturz mitten in der Erneuerung aufräumen.

    ``True``, wenn wiederhergestellt wurde. Aufgerufen beim Start, **bevor**
    irgendetwas eine TLS-Verbindung versucht: sonst wäre die erste Meldung im
    Protokoll ein OpenSSL-Fehler, den niemand mit einer Erneuerung verbindet.
    """
    if not config.cert_path.exists() or not config.key_path.exists():
        return False
    if pair_matches(config.cert_path, config.key_path):
        return False

    prev_cert = config.cert_path.with_name(config.cert_path.name + PREV_SUFFIX)
    prev_key = config.key_path.with_name(config.key_path.name + PREV_SUFFIX)
    if not (prev_cert.exists() and prev_key.exists() and pair_matches(prev_cert, prev_key)):
        raise RenewalError(
            f"Zertifikat und Schlüssel in {config.state_dir} passen nicht zusammen, "
            "und es liegt keine brauchbare Sicherungskopie daneben. Eine "
            "Erneuerung ist wohl mitten im Wechsel abgebrochen. Den Agenten in "
            "der Konsole widerrufen und neu anmelden."
        )
    logger.warning(
        "Zertifikat und Schlüssel passten nicht zusammen — eine Erneuerung ist "
        "mitten im Wechsel abgebrochen. Das vorherige Paar wird "
        "wiederhergestellt; die Erneuerung wird erneut versucht."
    )
    write_secret_file(config.key_path, prev_key.read_text(encoding="utf-8"))
    config.cert_path.write_text(prev_cert.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def renew(
    config: AgentConfig,
    secrets: AgentSecrets,
    *,
    agent_version: str,
    common_name: str = "magister-connector-agent",
    transport: httpx.BaseTransport | None = None,
) -> RenewalResult:
    """Neues Schlüsselpaar erzeugen und Zertifikat erneuern.

    Scheitert irgendetwas davor, dass beide Dateien getauscht sind, bleibt das
    bestehende Paar unverändert in Kraft.
    """
    key_pem, csr_pem = generate_key_and_csr(common_name)

    context = build_context(ca_bundle=config.ca_bundle, cert=config.cert_path, key=config.key_path)
    try:
        with httpx.Client(
            timeout=60.0,
            verify=context,
            trust_env=False,
            proxy=config.proxy,
            transport=transport,
            headers={"X-Connector-Api-Key": secrets.api_key},
        ) as client:
            resp = client.post(
                f"{config.endpoint}/connector/renew",
                json={"csr_pem": csr_pem, "agent_version": agent_version},
            )
    except httpx.HTTPError as exc:
        raise RenewalError(f"Die Plattform ist nicht erreichbar: {exc}") from exc

    if resp.status_code == 401:
        raise RenewalError(
            "Die Plattform hat den Agenten abgewiesen (401). Ist er in der "
            "Konsole widerrufen oder der Kunde gesperrt? Eine Erneuerung "
            "bringt einen widerrufenen Agenten nicht zurück — das ist Absicht."
        )
    if resp.status_code != 200:
        raise RenewalError(f"Erneuerung abgelehnt (HTTP {resp.status_code}): {_detail(resp)}")

    body = resp.json()
    certificate_pem = str(body["certificate_pem"])
    local = spki_fingerprint_from_certificate(certificate_pem)
    remote = str(body["spki_sha256"])
    if local != remote:
        raise RenewalError(
            "Das erneuerte Zertifikat passt nicht zum lokal erzeugten Schlüssel "
            f"(erwartet {local}, erhalten {remote}). Es wird nichts gespeichert."
        )

    _install(config, certificate_pem=certificate_pem, key_pem=key_pem.decode("ascii"))
    save_secrets(
        config,
        AgentSecrets(
            agent_id=secrets.agent_id,
            api_key=secrets.api_key,
            result_hmac_key=secrets.result_hmac_key,
            spki_sha256=remote,
        ),
    )
    not_after = dt.datetime.fromisoformat(str(body["certificate_not_after"]))
    logger.info(
        "Zertifikat erneuert. Neuer SPKI %s, gültig bis %s. Der alte Fingerprint "
        "gilt noch bis %s — kommt die Erneuerung nicht an, wird sie wiederholt.",
        remote,
        not_after.isoformat(),
        body.get("previous_valid_until", "?"),
    )
    return RenewalResult(spki_sha256=remote, certificate_not_after=not_after)


def _install(config: AgentConfig, *, certificate_pem: str, key_pem: str) -> None:
    """Das neue Paar in Kraft setzen, mit Sicherungskopie des alten.

    Reihenfolge: Kopie des alten Paares, dann Zertifikat, dann Schlüssel.

    Der Schlüssel zuletzt, weil in dieser Reihenfolge das **alte** Paar länger
    vollständig bleibt — und weil ``recover_if_broken`` beim Start ohnehin
    beide Fälle abfängt.
    """
    prev_cert = config.cert_path.with_name(config.cert_path.name + PREV_SUFFIX)
    prev_key = config.key_path.with_name(config.key_path.name + PREV_SUFFIX)
    if config.cert_path.exists() and config.key_path.exists():
        prev_cert.write_text(config.cert_path.read_text(encoding="utf-8"), encoding="utf-8")
        write_secret_file(prev_key, config.key_path.read_text(encoding="utf-8"))

    config.cert_path.write_text(certificate_pem, encoding="utf-8")
    write_secret_file(config.key_path, key_pem)


def _detail(resp: httpx.Response) -> str:
    try:
        payload: object = resp.json()
    except ValueError:
        return resp.text[:200]
    if not isinstance(payload, dict):
        return resp.text[:200]
    detail: object = cast(dict[str, Any], payload).get("detail")
    return str(detail) if detail else resp.text[:200]


__all__ = [
    "PREV_SUFFIX",
    "RENEW_BEFORE_DAYS",
    "RETRY_AFTER",
    "RenewalError",
    "RenewalResult",
    "certificate_not_after",
    "days_until_expiry",
    "is_due",
    "pair_matches",
    "recover_if_broken",
    "renew",
]
