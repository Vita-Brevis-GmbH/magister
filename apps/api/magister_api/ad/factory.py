"""Welcher AD-Rücken für diesen Kunden gilt — an genau einer Stelle (ADR-0022 D2).

Es gibt drei Wege ins Verzeichnis (ADR-0011, ADR-0014), und die Wahl zwischen
ihnen ist **eine** Entscheidung, auch wenn zwei Aufrufer sie brauchen: der
Anfragepfad (``routers/admin_sync.get_ad_client``) und die wiederkehrende
Schleife (``services/ad_sync_scheduler``).

**Warum das hier und nicht dort steht, wo es gebraucht wird:** es stand
dort — zweimal, und die zweite Stelle kannte den Connector nicht. Der
Anfragepfad wählte bei einem gehosteten Kunden den Agenten, die Schleife nahm
fest den direkten LDAP-Rücken und versuchte damit genau die Verbindung ins
Kundennetz, die es nach ADR-0014 nicht geben soll. Nicht aus Nachlässigkeit:
der dritte Rücken kam später dazu, und die ältere Schleife wurde nicht
mitgezogen. Eine Stelle kann man nicht halb aktualisieren.

Die Reihenfolge ist Absicht:

1. ``MAGISTER_AD_RPC_URL`` gesetzt → ``AdRpcClient``. Die strenge AD-Grenze
   (ADR-0011): dieser Prozess hält keine Verzeichnis-Anmeldedaten.
2. Connector aktiviert und der Kunde hat eine Konsolen-Id →
   ``AdConnectorClient``. Der gehostete Fall (ADR-0014): die Plattform öffnet
   nie eine Verbindung in das Kundennetz, der Agent klopft von innen an.
3. Sonst ``AdClient`` — direkt, für die Einzelinstallation.
"""

from __future__ import annotations

from magister_api.ad.client import AdClient
from magister_api.config import Settings
from magister_api.tenancy.registry import Tenant

#: Suffix der Registry-URL. Aus ihr wird die Basis-URL der Konsole abgeleitet,
#: statt eine zweite Einstellung zu pflegen, die davon abweichen kann.
_REGISTRY_SUFFIX = "/api/tenants/registry"


def console_base(registry_url: str) -> str:
    """Basis-URL der Konsole aus der Registry-URL ableiten."""
    if registry_url.endswith(_REGISTRY_SUFFIX):
        return registry_url[: -len(_REGISTRY_SUFFIX)]
    return registry_url.rstrip("/")


def build_ad_client(base: Settings, effective: Settings, tenant: Tenant) -> AdClient:
    """Den AD-Rücken für diesen Kunden bauen.

    ``base`` sind die Prozess-Einstellungen (dort stehen Transport und
    Anmeldung: RPC-URL, Connector-Schalter, Konsolen-Token), ``effective`` die
    über ``app_settings`` überlagerten des Kunden (dort stehen Suchbasis,
    Domänencontroller, Dienstkonto). Beide werden gebraucht, und sie sind
    nicht dasselbe: die Verbindung zur Konsole gehört der Installation, das
    Verzeichnis gehört dem Kunden.

    Der Aufrufer schliesst den Client (``aclose``) — die entfernten Rücken
    halten einen HTTP-Pool.
    """
    if base.ad_rpc_url and base.ad_rpc_secret is not None:
        # Träge importiert, damit der direkte Weg keinen httpx-Import trägt.
        from magister_api.ad.rpc_client import AdRpcClient

        return AdRpcClient(
            effective,
            base_url=base.ad_rpc_url,
            secret=base.ad_rpc_secret.get_secret_value(),
        )
    if base.ad_connector_enabled and base.console_registry_url and tenant.console_id:
        from magister_api.ad.connector_client import AdConnectorClient

        return AdConnectorClient(
            effective,
            console_url=console_base(base.console_registry_url),
            token=base.console_registry_token.get_secret_value(),
            tenant_id=tenant.console_id,
            management_marker=base.console_management_marker.get_secret_value(),
        )
    return AdClient(effective)


__all__ = ["build_ad_client", "console_base"]
