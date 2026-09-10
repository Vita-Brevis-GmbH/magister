"""Systemeinstellungen als Soll-Zustand (ADR-0017 D2).

Die Konsole besitzt die **Politik**, nicht die Geheimnisse. Was das im
Einzelnen heisst, steht in `POLICY_KEYS`: eine ausdrückliche Liste der
Schlüssel, die hier gesetzt werden dürfen.

**Warum eine Liste und kein Namensfilter.** Der naheliegende Entwurf war eine
Regel wie „alles mit `password`, `secret`, `key` oder `pem` im Namen ist
verboten". Sie ist falsch, in beide Richtungen:

* `password_store_enabled` ist ein **Schalter**, kein Passwort. Ein
  Namensfilter hätte ihn abgelehnt, und die Konsole könnte den
  Passwortspeicher eines Kunden nicht freischalten.
* `ad_tls_ca_pem` und `web_tls_cert_pem` sind **öffentliche** Zertifikate. Sie
  gehören zur Politik. `web_tls_key_pem` gehört nicht dazu — der Name
  unterscheidet sie um drei Zeichen.

Also ist die Allowlist die Autorität. Der Namensfilter existiert trotzdem,
aber an einer anderen Stelle: als **Test** über die Allowlist selbst
(`tests/test_settings.py`). Kommt später ein Schlüssel dazu, der wie ein
Geheimnis aussieht, schlägt der Test fehl und verlangt eine begründete
Ausnahme. Das ist die Prüfung zum richtigen Zeitpunkt — beim Hinzufügen, nicht
beim Schreiben.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models.settings import PlatformSettings, TenantSettings

#: Die Politik-Schlüssel, die die Konsole für einen Kunden setzen darf, mit
#: ihrem erwarteten Typ. Die Namen sind die der Datenebene
#: (`magister_api.schemas.app_settings.AppSettingsUpdate`) — bewusst identisch,
#: damit der Reconciler nicht übersetzen muss und eine Umbenennung dort hier
#: auffällt.
POLICY_KEYS: dict[str, type | tuple[type, ...]] = {
    # Anmeldung
    "oidc_issuer": str,
    "oidc_client_id": str,
    "oidc_redirect_uri": str,
    "oidc_scopes": list,
    "bootstrap_admins": list,
    "mail_domains": list,
    # Verzeichnis
    "ad_dcs": list,
    "ad_bind_mode": str,
    "ad_bind_dn": str,
    "ad_tls_verify": bool,
    #: Öffentliches CA-Zertifikat, gegen das das LDAPS-Zertifikat des Kunden
    #: geprüft wird. Kein Geheimnis.
    "ad_tls_ca_pem": str,
    "ad_users_search_base": str,
    "ad_computers_search_base": str,
    "ad_groups_search_base": str,
    "ad_sync_interval_minutes": int,
    "ad_ou_students_other": str,
    "ad_ou_teachers": str,
    "ad_groups_teacher": list,
    # Betrieb
    #: Ein Schalter, kein Passwort: er entscheidet, ob der Passwortspeicher
    #: überhaupt benutzt wird.
    "password_store_enabled": bool,
    "instance_profile": str,
    "module_overrides": dict,
    # NinjaOne
    "ninja_enabled": bool,
    "ninja_region": str,
    "ninja_client_id": str,
    #: Öffentlicher Teil des Webserver-Zertifikats. Der private Schlüssel
    #: (`web_tls_key_pem`) steht ausdrücklich NICHT hier.
    "web_tls_cert_pem": str,
}

#: Was nach einem Geheimnis aussieht. Wird zur Laufzeit **nicht** angewandt —
#: die Allowlist oben entscheidet. Der Test über die Allowlist benutzt dieses
#: Muster, damit ein künftiger Eintrag mit einem solchen Namen eine
#: ausdrückliche Begründung verlangt.
SECRET_LOOKING = re.compile(r"(secret|passwd|private|_enc$|_key$|_key_|password)", re.I)

#: Begründete Ausnahmen zum Muster oben. Wer hier etwas einträgt, schreibt den
#: Grund dazu — und der Grund muss lauten: „ist kein Geheimnis".
SECRET_LOOKING_EXEMPT: dict[str, str] = {
    "password_store_enabled": (
        "Schalter, kein Passwort: entscheidet, ob der Passwortspeicher benutzt wird."
    ),
}


class SettingsError(ValueError):
    """Ein Dokument, das so nicht gespeichert werden darf."""


def validate_policy(document: dict[str, Any]) -> dict[str, Any]:
    """Prüft ein Politik-Dokument und gibt es unverändert zurück.

    Drei Ablehnungsgründe, jeder mit dem Namen des Feldes in der Meldung —
    eine Fehlermeldung, die „ungültige Eingabe" sagt, kostet den Betreiber
    genau die Zeit, die diese Zeilen sparen.
    """
    if not isinstance(document, dict):
        raise SettingsError("Die Einstellungen müssen ein Objekt sein.")
    for key, value in document.items():
        expected = POLICY_KEYS.get(key)
        if expected is None:
            raise SettingsError(
                f"'{key}' ist kein Politik-Schlüssel. Erlaubt sind: "
                f"{', '.join(sorted(POLICY_KEYS))}. Geheimnisse (Passwörter, "
                "Client-Secrets, private Schlüssel) gehören nicht in die Konsole — "
                "sie werden auf dem Anwendungsserver gesetzt (ADR-0017 D2)."
            )
        if value is None:
            # Ausdrücklich erlaubt: ein `null` heisst „auf den Vorgabewert
            # zurück" beziehungsweise „leer". Es ist die einzige Möglichkeit,
            # eine Abweichung wieder aufzuheben.
            continue
        # bool ist in Python eine Unterklasse von int — ohne diese Zeile
        # ginge `true` als Wert für ein Intervall durch.
        if expected is int and isinstance(value, bool):
            raise SettingsError(f"'{key}' erwartet eine Zahl, nicht einen Wahrheitswert.")
        if not isinstance(value, expected):
            name = expected.__name__ if isinstance(expected, type) else str(expected)
            raise SettingsError(f"'{key}' erwartet {name}, bekam {type(value).__name__}.")
    return document


def validate_rbac(matrix: dict[str, Any] | None) -> dict[str, Any] | None:
    """Prüft eine Rechte-Matrix: {rollen_schlüssel: [capability, ...]}.

    Welche Capabilities es gibt, weiss die **Datenebene** — sie führt die
    Aufzählung. Hier wird deshalb nur die Form geprüft. Ein unbekannter
    Capability-Name fällt beim Materialisieren auf, und dort gehört er auch
    hin: die Konsole soll nicht bei jeder neuen Capability nachgezogen werden
    müssen.
    """
    if matrix is None:
        return None
    if not isinstance(matrix, dict):
        raise SettingsError("Die Rechte-Matrix muss ein Objekt sein.")
    for role, caps in matrix.items():
        if not isinstance(role, str) or not role:
            raise SettingsError("Jeder Rollenschlüssel muss eine nicht-leere Zeichenkette sein.")
        if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            raise SettingsError(f"Die Rechte von '{role}' müssen eine Liste von Namen sein.")
    return matrix


def effective(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Vorgabe, feldweise von den Abweichungen überschrieben.

    Feldweise und nicht als Ganzes: sonst müsste eine Abweichung die
    vollständige Vorgabe mitschleppen und würde bei der nächsten Änderung der
    Vorgabe stillschweigend veralten.

    Ein `None` in den Abweichungen hebt die Abweichung auf und lässt die
    Vorgabe gelten — nicht „setze auf null". Ohne diese Unterscheidung gäbe es
    keinen Weg zurück zur Vorgabe.
    """
    merged = dict(defaults)
    for key, value in overrides.items():
        if value is None:
            # **Überspringen**, nicht entfernen. Der erste Entwurf stand hier
            # `merged.pop(key)` — das löschte die Vorgabe mit und machte aus
            # „zurück zur Vorgabe" ein „Feld weg". Der eigene Test hat es
            # gefunden, bevor ein Kunde ohne Sync-Intervall dastand.
            continue
        merged[key] = value
    return merged


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def platform(self) -> PlatformSettings:
        """Die Vorgaben-Zeile, bei Bedarf angelegt."""
        row = await self.session.get(PlatformSettings, 1)
        if row is None:
            row = PlatformSettings(id=1, defaults={}, rbac={})
            self.session.add(row)
            await self._flush_and_load(row)
        return row

    async def _flush_and_load(self, row: PlatformSettings | TenantSettings) -> None:
        """Schreiben und die serverseitig erzeugten Werte nachladen.

        `updated_at` kommt aus `now()` der Datenbank. SQLAlchemy weiss nach dem
        Flush, dass der Wert veraltet ist, und lädt ihn beim nächsten Zugriff
        nach — nur ist das ein **await** mitten in der Serialisierung, und dort
        endet es in `MissingGreenlet: greenlet_spawn has not been called`. Eine
        Fehlermeldung, die nach einem Nebenläufigkeitsproblem aussieht und eine
        fehlende Zeile ist.

        Also ausdrücklich hier nachladen, wo ein `await` hingehört.
        """
        await self.session.flush()
        await self.session.refresh(row)

    async def set_platform(
        self,
        *,
        defaults: dict[str, Any] | None = None,
        rbac: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> PlatformSettings:
        row = await self.platform()
        if defaults is not None:
            row.defaults = validate_policy(defaults)
        if rbac is not None:
            row.rbac = validate_rbac(rbac) or {}
        row.updated_by = actor
        await self._flush_and_load(row)
        return row

    async def tenant(self, tenant_id: UUID) -> TenantSettings | None:
        stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def set_tenant(
        self,
        tenant_id: UUID,
        *,
        overrides: dict[str, Any] | None = None,
        rbac: dict[str, Any] | None = None,
        clear_rbac: bool = False,
        actor: str | None = None,
    ) -> TenantSettings:
        row = await self.tenant(tenant_id)
        if row is None:
            row = TenantSettings(tenant_id=tenant_id, overrides={})
            self.session.add(row)
        if overrides is not None:
            row.overrides = validate_policy(overrides)
        if clear_rbac:
            # Ausdrücklich, nicht über `rbac=None`: `None` heisst „nicht
            # angefasst". Ohne diesen Unterschied liesse sich eine eigene
            # Matrix nie wieder auf die globale zurücksetzen.
            row.rbac = None
        elif rbac is not None:
            row.rbac = validate_rbac(rbac)
        row.updated_by = actor
        await self._flush_and_load(row)
        return row

    async def desired_state(self, tenant_id: UUID) -> dict[str, Any]:
        """Was für diesen Kunden gelten soll — so, wie die Datenebene es holt.

        Die Rechte-Matrix wird **ganz** ersetzt, wenn der Kunde eine eigene
        hat, sonst gilt die globale. Eine feldweise gemischte Rechte-Matrix
        wäre eine, die niemand mehr lesen kann.
        """
        platform = await self.platform()
        tenant = await self.tenant(tenant_id)
        overrides = tenant.overrides if tenant else {}
        rbac = tenant.rbac if tenant and tenant.rbac is not None else platform.rbac
        return {
            "settings": effective(platform.defaults, overrides),
            "rbac": rbac or {},
            "settings_source": "tenant" if overrides else "platform",
            "rbac_source": "tenant" if (tenant and tenant.rbac is not None) else "platform",
        }


__all__ = [
    "POLICY_KEYS",
    "SECRET_LOOKING",
    "SECRET_LOOKING_EXEMPT",
    "SettingsError",
    "SettingsService",
    "effective",
    "validate_policy",
    "validate_rbac",
]
