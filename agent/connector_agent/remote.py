"""Die Konfiguration aus dem Cockpit (ADR-0014, Nachtrag „Agent auf dem DC").

Alles, was der Agent zum Arbeiten braucht, wird im Cockpit beim Kunden
gepflegt: OU-Freigabe, zusätzliche geschützte Gruppen, Domänencontroller,
Suchbasen, LDAPS-Vertrauensanker. Der Agent holt es über den beglaubigten
Kanal (``GET /connector/config``) und legt die letzte gültige Fassung in sein
Zustandsverzeichnis — damit er nach einem Neustart auch dann arbeitet, wenn
die Plattform gerade nicht antwortet.

Kein Geheimnis darin. Der Agent läuft auf dem Domänencontroller als
LocalSystem und bindet sich als **Maschinenkonto des DC** per Kerberos ans AD
(SASL/GSSAPI über LDAPS). Es gibt kein Dienstkonto und kein Passwort, das
irgendwo liegt — und damit keinen Grund, das Tiering zu brechen: der Agent
verlässt Tier 0 nicht.

Was aus dem Cockpit kommt, wird hier **noch einmal geprüft**. Eine Freigabe
auf die ganze Domäne oder auf ``Domain Controllers`` verwirft der Agent, auch
wenn das Cockpit sie schickt; die eingebauten geschützten Gruppen bleiben
immer gesperrt (siehe :mod:`connector_agent.guardrails`).
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx

from connector_agent.config import AgentConfig, AgentSecrets, write_secret_file
from connector_agent.guardrails import DEFAULT_PROTECTED_GROUPS, Guardrails, refusal_for_base
from connector_agent.tls import build_context

logger = logging.getLogger(__name__)

#: Dateiname der zwischengespeicherten Fassung im Zustandsverzeichnis.
CACHE_FILE = "remote-config.json"

#: Wie oft der Dienst nach einer neuen Fassung fragt. Fünf Minuten: eine
#: Änderung im Cockpit soll ohne Neustart greifen, aber nicht jeder Long-Poll
#: braucht einen zweiten Aufruf.
REFRESH_SECONDS = 300.0


class RemoteConfigError(RuntimeError):
    """Die Konfiguration liess sich nicht holen oder ist unbrauchbar."""


@dataclass(frozen=True, slots=True)
class RemoteAd:
    """AD-Zugang, wie das Cockpit ihn vorgibt. Ohne Bind-Daten: Kerberos."""

    #: Leer heisst: dieser DC selbst (siehe :func:`local_dc_fqdn`).
    dcs: tuple[str, ...] = ()
    users_search_base: str | None = None
    computers_search_base: str | None = None
    tls_verify: bool = True
    tls_ca_pem: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteConfig:
    allowed_ous: frozenset[str]
    #: Bereits mit :data:`DEFAULT_PROTECTED_GROUPS` vereinigt.
    protected_groups: frozenset[str]
    ad: RemoteAd = field(default_factory=RemoteAd)
    poll_seconds: int = 25
    revision: str = ""
    #: Freigaben, die der Agent verworfen hat, mit Grund — für Protokoll und
    #: ``check``. Steht etwas darin, stimmt das Cockpit nicht mit dem Agenten
    #: überein, und das soll man sehen.
    refused_ous: tuple[tuple[str, str], ...] = ()

    @property
    def guardrails(self) -> Guardrails:
        return Guardrails(allowed_ous=self.allowed_ous, protected_groups=self.protected_groups)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in cast(list[object], value) if str(v).strip()]


def _opt(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def parse(raw: dict[str, Any]) -> RemoteConfig:
    """Antwort des Cockpits in eine geprüfte Konfiguration übersetzen."""
    allowed: set[str] = set()
    refused: list[tuple[str, str]] = []
    for dn in _strings(raw.get("allowed_ous")):
        reason = refusal_for_base(dn)
        if reason is None:
            allowed.add(dn)
        else:
            refused.append((dn, reason))
    groups = DEFAULT_PROTECTED_GROUPS | {g.lower() for g in _strings(raw.get("protected_groups"))}
    ad_raw: object = raw.get("ad")
    ad_map = cast(dict[str, Any], ad_raw) if isinstance(ad_raw, dict) else {}
    ad = RemoteAd(
        dcs=tuple(_strings(ad_map.get("dcs"))),
        users_search_base=_opt(ad_map.get("users_search_base")),
        computers_search_base=_opt(ad_map.get("computers_search_base")),
        tls_verify=ad_map.get("tls_verify") is not False,
        tls_ca_pem=_opt(ad_map.get("tls_ca_pem")),
    )
    try:
        poll = int(raw.get("poll_seconds") or 25)
    except (TypeError, ValueError):
        poll = 25
    return RemoteConfig(
        allowed_ous=frozenset(allowed),
        protected_groups=frozenset(groups),
        ad=ad,
        poll_seconds=min(max(poll, 5), 60),
        revision=str(raw.get("revision") or ""),
        refused_ous=tuple(refused),
    )


def _decode(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 401:
        raise RemoteConfigError(
            "Die Plattform hat den Agenten abgewiesen (401). Ist er in der Konsole "
            "widerrufen oder der Kunde gesperrt?"
        )
    if resp.status_code != 200:
        raise RemoteConfigError(f"Konfiguration nicht geholt (HTTP {resp.status_code}).")
    try:
        body: object = resp.json()
    except ValueError as exc:
        raise RemoteConfigError("Antwort der Plattform ist kein JSON.") from exc
    if not isinstance(body, dict):
        raise RemoteConfigError("Antwort der Plattform ist kein JSON-Objekt.")
    return cast(dict[str, Any], body)


async def fetch(client: httpx.AsyncClient) -> tuple[RemoteConfig, dict[str, Any]]:
    """Über den laufenden Kanal des Dienstes holen. Rückgabe: (geprüft, roh)."""
    raw = _decode(await client.get("/connector/config"))
    return parse(raw), raw


def fetch_sync(
    config: AgentConfig,
    secrets: AgentSecrets,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[RemoteConfig, dict[str, Any]]:
    """Dasselbe für die Kommandozeile (``enroll``, ``check``)."""
    context = build_context(ca_bundle=config.ca_bundle, cert=config.cert_path, key=config.key_path)
    with httpx.Client(
        base_url=config.endpoint,
        timeout=30.0,
        verify=context,
        trust_env=False,
        proxy=config.proxy,
        transport=transport,
        headers={"X-Connector-Api-Key": secrets.api_key},
    ) as client:
        raw = _decode(client.get("/connector/config"))
    return parse(raw), raw


def cache_path(config: AgentConfig) -> Path:
    return config.state_dir / CACHE_FILE


def save_cache(config: AgentConfig, raw: dict[str, Any]) -> None:
    """Letzte gültige Fassung ablegen. Kein Geheimnis — aber im selben
    abgedichteten Verzeichnis, mit denselben Rechten wie alles dort."""
    write_secret_file(cache_path(config), json.dumps(raw, indent=2, sort_keys=True))


def load_cache(config: AgentConfig) -> RemoteConfig | None:
    path = cache_path(config)
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return parse(cast(dict[str, Any], raw))


def local_dc_fqdn() -> str:
    """Voller Name dieses Servers — der DC, auf dem der Agent läuft.

    Kerberos verlangt den Namen, nicht die IP: das Dienstticket lautet auf
    ``ldap/<fqdn>``. ``localhost`` ginge über LDAPS ohnehin nicht, weil das
    Zertifikat des DC auf seinen Namen ausgestellt ist.
    """
    return socket.getfqdn()


def ad_settings_kwargs(remote: RemoteConfig) -> dict[str, Any]:
    """Felder für ``magister_api.config.Settings`` — nur AD, nur aus dem Cockpit."""
    return {
        "ad_dcs": list(remote.ad.dcs) or [local_dc_fqdn()],
        "ad_bind_mode": "gssapi",
        "ad_bind_dn": None,
        "ad_bind_password": None,
        "ad_users_search_base": remote.ad.users_search_base,
        "ad_computers_search_base": remote.ad.computers_search_base,
        "ad_tls_verify": remote.ad.tls_verify,
        "ad_tls_ca_pem": remote.ad.tls_ca_pem,
    }


def describe(remote: RemoteConfig) -> str:
    """Eine Zeile fürs Protokoll. Nennt Anzahlen, keine DNs."""
    dcs = ", ".join(remote.ad.dcs) or f"{local_dc_fqdn()} (dieser DC)"
    return (
        f"Konfiguration {remote.revision or '-'}: {len(remote.allowed_ous)} OU(s) freigegeben, "
        f"{len(remote.protected_groups)} geschützte Gruppe(n), DC {dcs}"
    )


__all__ = [
    "CACHE_FILE",
    "REFRESH_SECONDS",
    "RemoteAd",
    "RemoteConfig",
    "RemoteConfigError",
    "ad_settings_kwargs",
    "cache_path",
    "describe",
    "fetch",
    "fetch_sync",
    "load_cache",
    "local_dc_fqdn",
    "parse",
    "save_cache",
]
