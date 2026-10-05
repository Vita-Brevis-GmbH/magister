"""Der Hostname eines Kunden: gültig, unter der Plattform-Domäne, nicht reserviert.

Bisher wurde er nur kleingeschrieben. Angenommen wurde damit auch
`konsole.<domäne>` (der Name der Konsole), `connect.<domäne>` (der des
Connector-Kanals), ein Name mit Unterstrich (kein gültiger Hostname, kein
Zertifikat dafür) oder ein Tippfehler in der Domäne — und aufgefallen wäre
das erst, wenn die Kundenseite nicht lädt oder, schlimmer, ein Name der
Plattform beim Kunden landet.

Zwei Stufen, weil die zweite die Konfiguration braucht:

* :func:`check_syntax` — ein gültiger Hostname nach RFC 1123, keine IP.
  Läuft im Schema, ohne Kontext.
* :func:`check_placement` — unter der Plattform-Domäne, genau eine Ebene
  darunter (das Platzhalter-Zertifikat deckt nur eine), und kein Name, den
  die Plattform selbst trägt.
"""

from __future__ import annotations

import ipaddress
import re

#: Erste Labels, die immer der Plattform gehören — auch wenn die konkreten
#: Namen der Konsole und des Kanals einmal anders konfiguriert sind.
RESERVED_LABELS: frozenset[str] = frozenset({"konsole", "console", "connect"})

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class HostnameError(ValueError):
    """Der Hostname taugt nicht für einen Kunden. Die Meldung sagt, warum."""


def check_syntax(value: str) -> str:
    """Normalisiert (klein, ohne Leerraum, ohne Schlusspunkt) und prüft die Form."""
    host = value.strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise HostnameError(
            "hostname muss ein Name sein, keine IP-Adresse — das Zertifikat und die "
            "Zuordnung zum Kunden gehen über den Namen"
        )
    if len(host) > 253:
        raise HostnameError("hostname ist länger als 253 Zeichen")
    labels = host.split(".")
    if len(labels) < 2:
        raise HostnameError("hostname braucht mindestens eine Domäne (z. B. thun.magister.ch)")
    for label in labels:
        if not _LABEL.match(label):
            raise HostnameError(
                f"hostname: '{label}' ist kein gültiger Namensteil — erlaubt sind "
                "Kleinbuchstaben, Ziffern und Bindestrich (nicht am Anfang oder "
                "Ende), höchstens 63 Zeichen; kein Unterstrich"
            )
    return host


def check_placement(host: str, *, tenant_domain: str, platform_hosts: tuple[str, ...]) -> None:
    """Prüft den Hostnamen gegen die Plattform. Wirft :class:`HostnameError`."""
    taken = {h.strip().lower().rstrip(".") for h in platform_hosts if h.strip()}
    if host in taken:
        raise HostnameError(f"hostname '{host}' ist ein Name der Plattform selbst")
    first = host.split(".", 1)[0]
    if first in RESERVED_LABELS:
        raise HostnameError(
            f"hostname: '{first}' ist für die Plattform reserviert "
            f"({', '.join(sorted(RESERVED_LABELS))})"
        )
    domain = tenant_domain.strip().lower().strip(".")
    if not domain:
        return
    suffix = f".{domain}"
    if not host.endswith(suffix):
        raise HostnameError(f"hostname muss unter {domain} liegen (z. B. thun.{domain})")
    if "." in host[: -len(suffix)]:
        raise HostnameError(
            f"hostname muss genau eine Ebene unter {domain} liegen — das "
            f"Platzhalter-Zertifikat *.{domain} deckt keine zweite ab"
        )


__all__ = ["RESERVED_LABELS", "HostnameError", "check_placement", "check_syntax"]
