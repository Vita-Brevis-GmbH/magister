"""Registry von der Konsole beziehen (ADR-0013 D2, D4).

Die Konsole ist die Autorenstelle, die Datenebene hält eine Kopie. Zwei Regeln
bestimmen die Bauart:

**Kein Kunden-Request liest je die Konsolen-Datenbank.** Der Abruf passiert
beim Start und danach im Hintergrund; im heissen Pfad wird nur der Zwischen-
speicher gelesen.

**Ein Ausfall der Konsole lässt jeden Kunden weiterlaufen.** Ist die Konsole
nicht erreichbar, gilt der letzte gute Stand weiter. Ein leeres oder
fehlerhaftes Ergebnis ersetzt ihn **nicht** — sonst würde ein Fehler in der
Konsole alle Kunden auf 404 setzen. Das ist der Unterschied zwischen einer
Störung in der Verwaltung und einem Ausfall des Betriebs.

Die Konsole liefert **keine DSNs**, nur Verweise (``dsn_ref``). Den DSN setzt
die Datenebene aus ihrem eigenen Geheimnisspeicher zusammen:
``MAGISTER_TENANT_DSN_<REF>`` in Grossbuchstaben. Ein Abruf dieser Liste gibt
also niemandem Datenbankzugang — auch nicht, wenn der Kanal kompromittiert ist.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import httpx

from magister_api.tenancy.registry import (
    Tenant,
    TenantConfigError,
    TenantRegistry,
    TenantStatus,
)

logger = logging.getLogger(__name__)

#: Präfix der Umgebungsvariablen, in denen die DSNs liegen.
DSN_ENV_PREFIX = "MAGISTER_TENANT_DSN_"


class ConsoleUnavailableError(RuntimeError):
    """Die Konsole war nicht erreichbar oder hat nichts Brauchbares geliefert.

    Kein Betriebsfehler: der Aufrufer behält seinen letzten guten Stand.
    """


def dsn_env_name(dsn_ref: str) -> str:
    return f"{DSN_ENV_PREFIX}{dsn_ref.upper()}"


def resolve_dsn(dsn_ref: str, *, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    value = env.get(dsn_env_name(dsn_ref), "").strip()
    if not value:
        raise TenantConfigError(
            f"Für den Verweis {dsn_ref!r} fehlt {dsn_env_name(dsn_ref)}. Die Konsole "
            "liefert absichtlich keinen DSN — er kommt aus dem Geheimnisspeicher "
            "der Datenebene."
        )
    return value


def registry_from_console_payload(
    payload: list[dict[str, Any]], *, environ: Mapping[str, str] | None = None
) -> TenantRegistry:
    """Antwort der Konsole in eine Registry übersetzen.

    Ein Kunde, für den kein DSN hinterlegt ist, wird **übersprungen** und
    gemeldet, nicht als Fehler behandelt: sonst hielte ein einzelner
    unfertiger Eintrag in der Konsole die ganze Installation an. Er ist danach
    unbekannt und antwortet mit 404 — was zutrifft, denn erreichen könnte man
    ihn ohnehin nicht.
    """
    tenants: list[Tenant] = []
    skipped: list[str] = []
    for entry in payload:
        slug = str(entry.get("slug", "")).strip()
        if not slug:
            skipped.append("(ohne slug)")
            continue
        try:
            dsn = resolve_dsn(str(entry.get("dsn_ref") or slug), environ=environ)
        except TenantConfigError as exc:
            skipped.append(f"{slug}: {exc}")
            continue
        try:
            status = TenantStatus(str(entry.get("status", TenantStatus.ACTIVE.value)))
        except ValueError:
            skipped.append(f"{slug}: unbekannter Status {entry.get('status')!r}")
            continue
        tenants.append(
            Tenant(
                slug=slug,
                name=str(entry.get("name") or slug),
                dsn=dsn,
                schema_name=str(entry.get("schema_name") or f"t_{slug}"),
                db_role=str(entry.get("db_role") or "") or None,
                schema_version=str(entry.get("schema_version") or ""),
                status=status,
                hostname=str(entry.get("hostname") or "").lower() or None,
            )
        )
    if skipped:
        logger.warning(
            "Konsolen-Registry: %d Eintrag/Einträge übersprungen — %s",
            len(skipped),
            "; ".join(skipped),
        )
    if not tenants:
        raise ConsoleUnavailableError(
            "Die Konsole hat keinen brauchbaren Mandanten geliefert. Der letzte "
            "gute Stand bleibt in Kraft."
        )
    # Die Validierung der Registry gilt unverändert: die Konsole ist eine
    # Quelle, keine Autorität. Ein Eintrag, der die Trennungsregeln verletzt,
    # wird hier abgelehnt und nicht bedient.
    return TenantRegistry(tenants)


async def fetch_registry(
    url: str,
    *,
    token: str,
    timeout_s: float = 5.0,
    management_marker: str = "",
) -> TenantRegistry:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if management_marker:
        # Die Konsole verwirft alles ohne diesen Marker (ADR-0015 D1). Die
        # Datenebene spricht sie über das Management-Netz an, nicht über das
        # Internet.
        headers["X-Magister-Management"] = management_marker
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ConsoleUnavailableError(f"Konsole nicht erreichbar: {exc}") from exc
    if response.status_code != 200:
        # Kein Token im Text: die Antwort geht in den Log.
        raise ConsoleUnavailableError(
            f"Konsole antwortete mit HTTP {response.status_code} auf die Registry-Abfrage."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ConsoleUnavailableError(f"Antwort der Konsole ist kein JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise ConsoleUnavailableError("Antwort der Konsole ist keine Liste von Mandanten.")
    return registry_from_console_payload(payload)
