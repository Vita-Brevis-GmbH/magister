"""TLS-Kontext für den Connector-Kanal (ADR-0014).

Warum das ein eigenes Modul ist und nicht zwei Zeilen im Client: die
naheliegende Schreibweise **funktioniert nicht**, und zwar lautlos.

``httpx.Client(verify="ca.pem", cert=("agent.pem", "agent-key.pem"))`` ist die
Form, die in jedem Beispiel steht. Seit httpx 0.28 sind ``verify=<str>`` und
``cert=`` abgekündigt, und das Client-Zertifikat wird **nicht mehr
mitgeschickt** — der Server antwortet mit 401, als hätte man kein Zertifikat.
Keine Ausnahme, keine Warnung an der Stelle, an der es zählt.

Aufgefallen erst beim Lauf gegen einen echten Caddy: die Modultests benutzen
``MockTransport``, und der überspringt TLS vollständig. Ein Test, der den
Transport ersetzt, kann über den Transport nichts aussagen.

Deshalb hier ein ausdrücklicher ``ssl.SSLContext``: ``load_verify_locations``
für die Plattform-CA, ``load_cert_chain`` für das eigene Zertifikat. Das ist
der dokumentierte Weg ab httpx 0.28 und hat den Vorteil, dass ein fehlender
oder unlesbarer Schlüssel hier auffällt und nicht als 401 der Gegenseite.
"""

from __future__ import annotations

import ssl
from pathlib import Path


class TlsSetupError(RuntimeError):
    """Der TLS-Kontext liess sich nicht bauen."""


def build_context(
    *, ca_bundle: Path, cert: Path | None = None, key: Path | None = None
) -> ssl.SSLContext:
    """Kontext für den Kanal zur Plattform.

    ``ca_bundle`` prüft den Server: ohne diese Richtung könnte ein Angreifer im
    Netz die Plattform spielen und Aufträge erteilen. ``cert``/``key``
    authentisieren den Agenten; bei der Anmeldung gibt es sie noch nicht.
    """
    if ca_bundle.exists():
        context = ssl.create_default_context(cafile=str(ca_bundle))
    else:
        # Ohne mitgeliefertes Bundle gilt der System-Truststore. Zulässig,
        # wenn die Plattform ein öffentliches Zertifikat hat — aber es ist
        # nicht der vorgesehene Fall, deshalb kein stiller Vorgabewert im
        # Konfigurationsbeispiel.
        context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if cert is None:
        return context
    if key is None or not cert.exists() or not key.exists():
        raise TlsSetupError(
            f"Zertifikat oder Schlüssel fehlt ({cert}, {key}). Ohne beides kann "
            "sich der Agent nicht authentisieren."
        )
    try:
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    except (ssl.SSLError, OSError) as exc:
        raise TlsSetupError(
            f"Zertifikat und Schlüssel liessen sich nicht laden: {exc}. "
            "Gehören sie zusammen, und ist der Schlüssel lesbar?"
        ) from exc
    return context


__all__ = ["TlsSetupError", "build_context"]
