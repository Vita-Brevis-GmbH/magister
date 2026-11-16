"""Selbstprüfung der Anmeldung über den Realm (ADR-0025 Nachtrag 2026-11-16).

Fund aus dem Test: Magister hatte als Issuer die interne Adresse des Keycloak,
deren Zertifikat es nicht vertraute. Sichtbar wurde das erst, als sich jemand
anmelden wollte (`oidc_discovery_failed`); die öffentliche Adresse wäre
erreichbar gewesen. Deshalb prüft Magister die Anmeldung selbst, mit jeder
Zustandsmeldung, und meldet das Ergebnis dem Cockpit (Feld ``oidc``) — dort
zeigt „Kunde prüfen" den Fehler, bevor ein Benutzer ihn findet.

Geprüft wird, was eine Anmeldung braucht, bevor ein Benutzer im Spiel ist,
mit demselben HTTP-Client wie die Anmeldung (Vertrauen, Proxy):

1. Discovery unter ``<oidc_issuer>/.well-known/openid-configuration``: HTTP 200
   und ein JSON-Objekt;
2. ``issuer`` im Dokument gleich dem eingestellten ``oidc_issuer`` — Keycloak
   nennt den Issuer nach seinem Hostnamen, nicht nach der Adresse, unter der
   man ihn fragt; ein Unterschied heisst, Magister spricht den Realm unter
   einer anderen Adresse an, als er sich selbst nennt;
3. ``authorization_endpoint``, ``token_endpoint`` und ``jwks_uri`` vorhanden;
4. die JWKS abrufbar, mit mindestens einem Schlüssel;
5. ein Client-Secret gesetzt (nur ob, nie welches) — der Client des Cockpits
   ist vertraulich, ohne Secret weist Keycloak den Code-Tausch ab.

Der Grund (``reason``) ist ein festes Kürzel mit kurzer Art und dem Rechner,
höchstens 300 Zeichen, ohne Geheimnisse: ``discovery_tls: CERTIFICATE_VERIFY_FAILED:
… (auth.example.ch)``, ``discovery_http_404 (…)``, ``discovery_dns (…)``,
``issuer_mismatch: <Issuer im Dokument> (…)``, ``discovery_incomplete: jwks_uri (…)``,
``jwks_failed: http_404 (…)``, ``client_secret_missing``. Gemeldet wird der
erste Fehler in dieser Reihenfolge.

Nicht geprüft: ob der Client im Realm existiert und das Secret passt. Das
ginge nur mit einem Code-Tausch, und der hinterliesse alle paar Minuten einen
gescheiterten Anmeldeversuch im Realm des Kunden.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from magister_api.auth.oidc import (
    OidcDiscoveryError,
    StandardOidcClient,
    failure_kind,
    host_of,
    oidc_http,
)
from magister_api.config import Settings

logger = logging.getLogger(__name__)

#: Länge des Grundes, wie das Cockpit sie annimmt.
REASON_MAX = 300
#: Kürzer als bei der Anmeldung (10 s): die Prüfung läuft je Mandant
#: nacheinander in der Abgleichsschleife, ein hängender Anbieter soll die
#: übrigen nicht lange aufhalten.
CHECK_TIMEOUT_S = 5.0
_ENDPOINTS = ("authorization_endpoint", "token_endpoint", "jwks_uri")


def oidc_configured(settings: Settings) -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id)


def _result(*, configured: bool, reason: str | None, checked_at: datetime | None) -> dict[str, Any]:
    """Das Feld ``oidc`` der Zustandsmeldung — genau diese vier Schlüssel."""
    return {
        "configured": configured,
        "ok": None if not configured else reason is None,
        "reason": None if reason is None else reason[:REASON_MAX],
        "checked_at": None if checked_at is None else checked_at.isoformat(),
    }


async def check_oidc(
    settings: Settings, *, http: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Die Anmeldung über den Realm prüfen. Wirft nie; liest nur.

    ``settings`` sind die wirksamen Einstellungen des Mandanten (Konsole über
    Umgebung). Ohne Issuer oder Client-Id ist nichts eingerichtet:
    ``configured=false``, ``ok=null`` — kein Fehler, etwa vor dem Grundsetup.
    """
    if not oidc_configured(settings):
        return _result(configured=False, reason=None, checked_at=None)
    checked_at = datetime.now(UTC)
    own = http is None
    client = http if http is not None else oidc_http(CHECK_TIMEOUT_S)
    try:
        reason = await _first_problem(settings, client)
    except Exception as exc:
        # Ein Fehler der Prüfung selbst ist kein Befund über den Realm; er
        # darf die Zustandsmeldung nicht verhindern.
        logger.exception("Selbstprüfung der Anmeldung gescheitert")
        reason = f"check_failed: {type(exc).__name__}"
    finally:
        if own:
            await client.aclose()
    if reason is not None:
        logger.warning(
            "Anmeldung über den Realm nicht in Ordnung (%s): %s", settings.oidc_issuer, reason
        )
    return _result(configured=True, reason=reason, checked_at=checked_at)


async def _first_problem(settings: Settings, http: httpx.AsyncClient) -> str | None:
    issuer = settings.oidc_issuer
    host = host_of(issuer)
    try:
        meta = await StandardOidcClient(settings, http=http).discover()
    except OidcDiscoveryError as exc:
        return exc.reason

    named = meta.get("issuer")
    # Ohne Schrägstrich am Ende verglichen: die Anmeldung prüft `iss` gegen
    # das Dokument, ein Schrägstrich in der Einstellung stört sie nicht.
    if not isinstance(named, str) or named.rstrip("/") != issuer.rstrip("/"):
        shown = named if isinstance(named, str) and named else "-"
        return f"issuer_mismatch: {shown[:200]} ({host})"

    missing = [k for k in _ENDPOINTS if not _is_url(meta.get(k))]
    if missing:
        return f"discovery_incomplete: {', '.join(missing)} ({host})"

    jwks_uri = str(meta["jwks_uri"])
    try:
        resp = await http.get(jwks_uri)
        resp.raise_for_status()
        jwks: Any = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return f"jwks_failed: {failure_kind(exc)} ({host_of(jwks_uri)})"
    keys: Any = cast(dict[str, Any], jwks).get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list) or not keys:
        return f"jwks_failed: no_keys ({host_of(jwks_uri)})"

    if not settings.oidc_client_secret.get_secret_value():
        return "client_secret_missing"
    return None


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


__all__ = ["CHECK_TIMEOUT_S", "REASON_MAX", "check_oidc", "oidc_configured"]
