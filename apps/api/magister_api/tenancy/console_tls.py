"""TLS gegenüber der Konsole: wem die Datenebene vertraut.

Alle Wege zur Konsole (Registry, Soll-Zustand, Zustandsmeldung, Schemastand,
Connector-Aufträge) gehen über dieses eine ``verify``. Vorher nahm jeder
Client die öffentlichen Wurzeln von httpx. Gegen eine Konsole mit einem
Zertifikat aus der Plattform-CA scheiterte damit **jeder** Abruf an
``CERTIFICATE_VERIFY_FAILED``. Die Datenebene fiel still auf ihre
Ersatz-Registry zurück, und kein Kunde bekam je seinen Soll-Zustand.
"""

from __future__ import annotations

import ssl
from functools import lru_cache
from pathlib import Path

from magister_api.config import Settings, get_settings


class ConsoleTlsError(RuntimeError):
    """Der Vertrauensanker für die Konsole ist gesetzt, aber unbrauchbar."""


@lru_cache(maxsize=4)
def _context(path: str) -> ssl.SSLContext:
    if not Path(path).is_file():
        raise ConsoleTlsError(
            f"MAGISTER_CONSOLE_CA_FILE={path!r} gibt es nicht. Dort gehört die Wurzel "
            "der Plattform-CA hin (PEM)."
        )
    try:
        # Mit `cafile` lädt Python NUR diese Datei, keine Systemwurzeln.
        return ssl.create_default_context(cafile=path)
    except ssl.SSLError as exc:
        raise ConsoleTlsError(
            f"MAGISTER_CONSOLE_CA_FILE={path!r} ist kein brauchbares PEM: {exc}"
        ) from exc


def console_verify(settings: Settings | None = None) -> ssl.SSLContext | bool:
    """Das ``verify`` für jeden httpx-Client, der die Konsole anspricht."""
    path = (settings or get_settings()).console_ca_file.strip()
    return _context(path) if path else True


__all__ = ["ConsoleTlsError", "console_verify"]
