"""Ergebnis an die Konsole melden.

Gemeinsam für ``verify_backup`` und ``restore_backup``. Ohne ``--console``
läuft beides trotzdem — dann steht das Ergebnis nur auf dem Terminal, und die
Konsole zeigt weiter „nie geprüft". Das ist die richtige Vorgabe für einen
Handlauf; für den Cron-Job gehört ``--console`` dazu.

Der Aufruf geht über den **Management-Listener** und braucht dessen Marker
(ADR-0015 D1). Ohne ihn antwortet die Konsole mit 404 — nicht mit 403, damit
eine Sonde am öffentlichen Ursprung nicht erfährt, dass dort eine Konsole
steht.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

#: Kurz gehalten: eine Meldung, die hängt, hält den Backup-Host auf.
TIMEOUT = 30.0


def report(
    *,
    console: str,
    path: str,
    ok: bool,
    detail: str,
    token: str,
    marker: str,
    ca_bundle: str | None = None,
) -> bool:
    """Ergebnis melden. ``True``, wenn die Konsole es angenommen hat.

    Ein Fehlschlag hier macht das Ergebnis nicht falsch — die Prüfung ist
    gelaufen. Deshalb nur eine Warnung und kein Abbruch: sonst sähe eine
    geglückte Prüfung mit unerreichbarer Konsole wie eine gescheiterte aus.
    """
    url = f"{console.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Magister-Management": marker,
    }
    try:
        with httpx.Client(timeout=TIMEOUT, verify=ca_bundle or True) as client:
            resp = client.post(url, headers=headers, params={"ok": ok, "detail": detail[:2000]})
    except httpx.HTTPError as exc:
        logger.warning("Konsole nicht erreichbar (%s): %s", url, exc)
        return False
    if resp.status_code != 200:
        logger.warning("Konsole hat die Meldung abgewiesen: HTTP %s", resp.status_code)
        return False
    return True


__all__ = ["TIMEOUT", "report"]
