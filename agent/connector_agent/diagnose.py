"""Warum der Kanal zur Plattform nicht zustande kommt — in einem Satz.

Vorher hiess jeder Verbindungsfehler „Die Plattform ist nicht erreichbar: …
Ist TCP 46200 ausgehend offen?". Bei der ersten echten Anmeldung war der Port
offen; der Agent sprach die Plattform über ihre IP-Adresse an, und das
Zertifikat gilt für einen Namen. Die Meldung schickte die Fehlersuche zur
Firewall, und `CERTIFICATE_VERIFY_FAILED` stand nur im Kleingedruckten.

Hier wird deshalb die Ursache aus der Ausnahmekette gelesen und **so benannt,
dass der nächste Handgriff klar ist**: ein Zertifikatsproblem nennt das
Zertifikat und den Namen, ein Netzproblem den Port, ein DNS-Problem den Namen.
Ein Hinweis auf die Firewall kommt nur noch dort, wo sie die Ursache sein kann.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from connector_agent.config import AgentConfig
from connector_agent.tls import TlsSetupError, build_context

#: OpenSSL-Prüfcodes (``X509_V_ERR_*``), nach denen hier unterschieden wird.
_HOSTNAME_MISMATCH = 62
_IP_ADDRESS_MISMATCH = 64
_CERT_HAS_EXPIRED = 10
_CERT_NOT_YET_VALID = 9
#: 7 (Signatur passt nicht) gehört dazu: eine neu erzeugte CA mit demselben
#: Namen wie die alte — Test-CA gegen echte CA — findet OpenSSL über den Namen
#: und scheitert dann an der Signatur. Für den Betreiber dieselbe Ursache.
_UNKNOWN_ISSUER = frozenset({2, 7, 19, 20, 21})


def endpoint_host_port(endpoint: str) -> tuple[str, int]:
    parts = urlsplit(endpoint)
    return parts.hostname or "", parts.port or 443


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def ip_endpoint_hint(endpoint: str) -> str | None:
    """Hinweis, wenn der Endpunkt eine IP-Adresse ist — sonst ``None``.

    Eine IP ist nicht verboten, aber fast immer falsch: das Zertifikat der
    Plattform ist auf einen Namen ausgestellt, und die Prüfung vergleicht
    genau diesen Namen mit dem, was im Endpunkt steht.
    """
    host, _port = endpoint_host_port(endpoint)
    if not is_ip_literal(host):
        return None
    return (
        f"Der Endpunkt nennt die IP-Adresse {host}. Das Zertifikat der Plattform "
        "gilt für einen Namen (z. B. connect.magister.ch) — als 'endpoint' muss "
        "dieser Name stehen. Löst er hier nicht auf, gehört er in den DNS oder "
        "in die hosts-Datei, nicht die IP in die Konfiguration."
    )


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _certificate_problem(err: ssl.SSLCertVerificationError, endpoint: str, ca: Path) -> str:
    host, _port = endpoint_host_port(endpoint)
    code = err.verify_code
    if code in (_HOSTNAME_MISMATCH, _IP_ADDRESS_MISMATCH):
        return (
            f"Das Zertifikat der Plattform gilt nicht für '{host}'. Als 'endpoint' "
            "muss genau der Name stehen, auf den das Zertifikat ausgestellt ist "
            "(steht in der Konsole beim Agenten-Download) — keine IP-Adresse und "
            "kein anderer Name desselben Servers. Der Port ist offen; an der "
            "Firewall liegt es nicht."
        )
    if code == _CERT_HAS_EXPIRED:
        return (
            "Das Zertifikat der Plattform ist abgelaufen — oder die Uhr dieses "
            "Servers geht falsch. Zuerst die Uhrzeit prüfen, dann Vita Brevis melden."
        )
    if code == _CERT_NOT_YET_VALID:
        return (
            "Das Zertifikat der Plattform ist noch nicht gültig. Fast immer geht "
            "die Uhr dieses Servers nach; Zeitsynchronisation prüfen."
        )
    if code in _UNKNOWN_ISSUER:
        return (
            "Das Zertifikat der Plattform stammt von einer Stelle, der dieser Server "
            f"nicht vertraut. 'ca_bundle' prüfen ({ca}): es muss das CA-Bündel aus "
            "dem Paket sein. Bricht ein Proxy oder eine Firewall TLS auf, muss sie "
            "diesen Namen ausnehmen — sonst kann sich der Agent nie anmelden."
        )
    message = err.verify_message or str(err)
    return f"Das Zertifikat der Plattform wurde abgelehnt: {message}."


def explain_transport_error(exc: BaseException, config: AgentConfig) -> str:
    """Ein Satz zur Ursache eines Verbindungsfehlers, mit dem nächsten Handgriff."""
    endpoint = config.endpoint
    host, port = endpoint_host_port(endpoint)
    chain = list(_chain(exc))
    for err in chain:
        if isinstance(err, ssl.SSLCertVerificationError):
            return _certificate_problem(err, endpoint, config.ca_bundle)
    for err in chain:
        if isinstance(err, socket.gaierror):
            return (
                f"Der Name '{host}' lässt sich auf diesem Server nicht auflösen. "
                "DNS prüfen (nslookup), oder den Namen in die hosts-Datei eintragen."
            )
        if isinstance(err, ConnectionRefusedError):
            return (
                f"Verbindung zu {host}:{port} abgewiesen. Dort nimmt nichts an, oder "
                "eine Firewall weist aktiv ab. Stimmt der Port im 'endpoint'?"
            )
    for err in chain:
        if isinstance(err, httpx.ProxyError):
            return f"Der Proxy ({config.proxy}) hat die Verbindung abgelehnt: {err}."
        if isinstance(err, httpx.ConnectTimeout | TimeoutError | socket.timeout):
            return (
                f"Keine Antwort von {host}:{port}. Meist blockiert eine Firewall "
                f"den ausgehenden Port {port} — von diesem Server aus prüfen."
            )
    for err in chain:
        if isinstance(err, ssl.SSLError):
            return (
                f"Der TLS-Handshake mit {host}:{port} ist gescheitert ({err.reason}). "
                "Häufige Ursache: ein Proxy oder eine Firewall, die TLS aufbricht, "
                "oder ein Endpunkt, hinter dem kein TLS spricht."
            )
    return f"Die Plattform ist nicht erreichbar ({host}:{port}): {exc}."


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    message: str


def probe_channel(config: AgentConfig, *, timeout: float = 10.0) -> ProbeResult:
    """TLS-Handshake mit der Plattform, ohne HTTP und ohne etwas zu verändern.

    Prüft genau das, woran eine Anmeldung zuerst scheitert: Name, Port und
    Zertifikat der Gegenseite. Der Kanal verlangt ein Client-Zertifikat; ohne
    Anmeldung bricht die Gegenseite den Handshake danach ab. Das ist hier ein
    **Erfolg** — die Prüfung des Servers ist zu dem Zeitpunkt schon gelaufen.
    """
    host, port = endpoint_host_port(config.endpoint)
    if config.proxy:
        return ProbeResult(
            True,
            f"übersprungen — der Kanal geht über den Proxy {config.proxy}; "
            "das Ergebnis steht nach dem Start im Dienstprotokoll",
        )
    cert = config.cert_path if config.cert_path.exists() else None
    try:
        context = build_context(
            ca_bundle=config.ca_bundle, cert=cert, key=config.key_path if cert else None
        )
    except TlsSetupError as exc:
        return ProbeResult(False, str(exc))
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            version = tls.version() or "TLS"
    except ssl.SSLCertVerificationError as exc:
        return ProbeResult(False, explain_transport_error(exc, config))
    except ssl.SSLError as exc:
        # Nach erfolgreicher Prüfung des Servers verweigert die Gegenseite den
        # Kanal ohne gültiges Client-Zertifikat. Genau das soll sie.
        if "ALERT" in (exc.reason or "").upper():
            return ProbeResult(
                True,
                f"{host}:{port} erreichbar, Zertifikat der Plattform gültig; "
                "der Kanal verlangt ein Client-Zertifikat",
            )
        return ProbeResult(False, explain_transport_error(exc, config))
    except OSError as exc:
        return ProbeResult(False, explain_transport_error(exc, config))
    return ProbeResult(
        True, f"{host}:{port} erreichbar, Zertifikat der Plattform gültig ({version})"
    )


__all__ = [
    "ProbeResult",
    "endpoint_host_port",
    "explain_transport_error",
    "ip_endpoint_hint",
    "is_ip_literal",
    "probe_channel",
]
