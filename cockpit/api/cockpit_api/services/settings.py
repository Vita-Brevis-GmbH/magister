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

from cockpit_api.models.operations import (
    MaintenanceState,
    PlatformSealedSecret,
    TenantMaintenanceRequest,
    TenantSealedSecret,
)
from cockpit_api.models.settings import PlatformSettings, TenantSettings
from cockpit_api.models.tenant import Tenant
from cockpit_api.services.modules import ModuleSettingsError, check_overrides, check_profile
from cockpit_api.services.templates import TemplateService

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
    # Mailversand (Erinnerung vor dem Passwort-Ablauf). Das Geheimnis —
    # SMTP-Passwort bzw. Graph-Client-Secret — steht NICHT hier, es reist
    # versiegelt als `mail_secret`.
    "mail_transport": str,
    "mail_from": str,
    "mail_from_name": str,
    "smtp_host": str,
    "smtp_port": int,
    "smtp_security": str,
    "smtp_username": str,
    "graph_tenant_id": str,
    "graph_client_id": str,
    "expiry_notice_enabled": bool,
    "expiry_notice_days": list,
}

#: Die Anbindung des Mailversands, mit dem Wert, der "leer" heisst. Sie gilt
#: **als Ganzes**: setzt ein Kunde auch nur ein Feld davon selbst, kommt die
#: ganze Anbindung aus seinen Abweichungen und das Plattform-Geheimnis geht
#: nicht hinaus. Feldweise gemischt hiesse: der Benutzername eines eigenen
#: SMTP-Servers mit dem Passwort von Vita Brevis — an einen fremden Server.
MAIL_CONNECTION_KEYS: dict[str, Any] = {
    "mail_transport": "off",
    "mail_from": "",
    "mail_from_name": "",
    "smtp_host": "",
    "smtp_port": 0,
    "smtp_security": "starttls",
    "smtp_username": "",
    "graph_tenant_id": "",
    "graph_client_id": "",
}

#: Geheimnisse, die zur Mail-Anbindung gehören.
MAIL_SECRET = "mail_secret"  # noqa: S105 — der Name, nicht der Wert


def has_own_mail(overrides: dict[str, Any]) -> bool:
    """Hat der Kunde eine eigene Mail-Anbindung (mindestens ein Feld gesetzt)?"""
    return any(overrides.get(key) is not None for key in MAIL_CONNECTION_KEYS)


def mail_connection(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Die geltende Anbindung, vollständig — fehlende Felder als "leer".

    Vollständig, damit beim Kunden nichts aus einer früheren Anbindung stehen
    bleibt: die Datenebene liest ein fehlendes Feld als "nicht anfassen".
    """
    source = overrides if has_own_mail(overrides) else defaults
    return {
        key: source[key] if source.get(key) is not None else blank
        for key, blank in MAIL_CONNECTION_KEYS.items()
    }


#: Früher hier gepflegt, jetzt nicht mehr: OUs und Gruppen für Schüler:innen
#: und Lehrpersonen. Sie gehören an den Standort bzw. an die Zielrollen im
#: Portal des Kunden — als eigenständige Objekte, unabhängig vom Profil (eine
#: Firma hat keine „OU Lehrpersonen"). Die Konsole setzt nur noch die
#: Suchbasen für Benutzer, Gruppen und Computer.
#:
#: Gespeicherte Altwerte werden still verworfen statt abgewiesen: sonst liesse
#: sich die Seite eines Kunden, bei dem einmal ein solcher Wert stand, nicht
#: mehr speichern. Ausgeliefert werden sie nicht mehr; was im Portal steht,
#: bleibt dort unberührt (der Abgleich fasst nur an, was die Konsole schickt).
RETIRED_KEYS: frozenset[str] = frozenset(
    {"ad_ou_students_other", "ad_ou_teachers", "ad_groups_teacher"}
)


def strip_retired(document: dict[str, Any]) -> dict[str, Any]:
    """Das Dokument ohne die nicht mehr gepflegten Schlüssel."""
    return {k: v for k, v in document.items() if k not in RETIRED_KEYS}


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
    """Prüft ein Politik-Dokument und gibt es ohne Altlasten zurück.

    Einzige Änderung am Dokument: Schlüssel aus :data:`RETIRED_KEYS` fallen weg.

    Drei Ablehnungsgründe, jeder mit dem Namen des Feldes in der Meldung —
    eine Fehlermeldung, die „ungültige Eingabe" sagt, kostet den Betreiber
    genau die Zeit, die diese Zeilen sparen.
    """
    if not isinstance(document, dict):
        raise SettingsError("Die Einstellungen müssen ein Objekt sein.")
    document = strip_retired(document)
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
    # Profil und Module tiefer als nach dem Typ: ein unbekanntes Modul oder
    # ein Schalter an der Basis würde sonst erst beim Kunden verworfen — und
    # die Konsole zeigte etwas an, das dort nie gilt.
    try:
        if document.get("instance_profile") is not None:
            check_profile(document["instance_profile"])
        if document.get("module_overrides") is not None:
            check_overrides(document["module_overrides"])
    except ModuleSettingsError as exc:
        raise SettingsError(str(exc)) from exc
    _check_mail(document)
    return document


def _check_mail(document: dict[str, Any]) -> None:
    """Die Mail-Werte so streng wie die Datenebene: sonst scheiterte der Abgleich dort."""
    transport = document.get("mail_transport")
    if transport is not None and transport not in {"off", "smtp", "graph"}:
        raise SettingsError("'mail_transport' muss off, smtp oder graph sein.")
    security = document.get("smtp_security")
    if security is not None and security not in {"starttls", "tls"}:
        raise SettingsError("'smtp_security' muss starttls oder tls sein (kein Klartext).")
    port = document.get("smtp_port")
    if port is not None and not 0 <= port <= 65535:
        raise SettingsError("'smtp_port' muss zwischen 0 (Vorgabe) und 65535 liegen.")
    sender = document.get("mail_from")
    if sender and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", sender):
        raise SettingsError("'mail_from' muss eine Mailadresse sein.")
    days = document.get("expiry_notice_days")
    if days is not None and (
        not 1 <= len(days) <= 5
        or any(isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 90 for d in days)
    ):
        raise SettingsError("'expiry_notice_days': 1 bis 5 Zahlen zwischen 1 und 90.")


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
    merged = strip_retired(defaults)
    for key, value in strip_retired(overrides).items():
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

    async def desired_state(self, tenant: Tenant) -> dict[str, Any]:
        """Was für diesen Kunden gelten soll — so, wie die Datenebene es holt.

        Die Rechte-Matrix wird **ganz** ersetzt, wenn der Kunde eine eigene
        hat, sonst gilt die globale. Eine feldweise gemischte Rechte-Matrix
        wäre eine, die niemand mehr lesen kann.

        Nimmt den Kunden und nicht seine Id: die Vorlagen-Zielgruppe fragt nach
        seinem Profil (ADR-0018 D5), und ein zweites Laden derselben Zeile wäre
        eine Abfrage, die nur deshalb existiert, weil die Signatur zu eng war.

        **Das Profil des Kunden gilt auch in seiner Installation.** Es steht in
        der Konsole am Kunden selbst (`tenants.profile`) — das ist der einzige
        Schalter, den die Oberfläche dafür anbietet. Ohne die Zeile unten blieb
        er auf halbem Weg stehen: er entschied die Vorlagen-Zielgruppe, und die
        Installation lief weiter im Profil aus den Plattform-Vorgaben. Auf dem
        Dev-Host stand der Kunde in der Konsole auf „company" und in seiner
        eigenen Oberfläche auf „Schule", ohne dass irgendwo ein Widerspruch
        gemeldet wurde.

        Rangfolge damit: **ausdrückliche Abweichung des Kunden > sein Profil in
        der Konsole > Plattform-Vorgabe.** Die Vorgabe zuletzt, weil ein
        globales „alle sind Schulen" sonst die Angabe am einzelnen Kunden
        überstimmen würde — und die ist die genauere.
        """
        platform = await self.platform()
        overrides_row = await self.tenant(tenant.id)
        overrides = overrides_row.overrides if overrides_row else {}
        own_rbac = overrides_row.rbac if overrides_row else None
        rbac = own_rbac if own_rbac is not None else platform.rbac
        settings = effective(platform.defaults, overrides)
        if "instance_profile" not in overrides:
            settings["instance_profile"] = str(tenant.profile)
        # Immer eine Aussage über die Modul-Schalter, auch eine leere. Ohne sie
        # blieb beim Kunden stehen, was dort vor der Konsole geschaltet wurde —
        # etwa „Klassen an" bei einem Kunden, der in der Konsole auf Firma
        # steht. Gehostet hat die Konsole das Feld allein (ADR-0017 Nachtrag).
        settings.setdefault("module_overrides", {})
        settings.update(mail_connection(platform.defaults, overrides))
        own_mail = has_own_mail(overrides)
        sealed = await self._sealed(tenant.id)
        if not own_mail:
            # Ein früher gesetztes eigenes Geheimnis gilt nicht mehr, sobald
            # die Anbindung wieder die der Plattform ist.
            sealed.pop(MAIL_SECRET, None)
        return {
            "settings": settings,
            "rbac": rbac or {},
            "templates": await TemplateService(self.session).desired_templates(tenant),
            "settings_source": "tenant" if overrides else "platform",
            "rbac_source": "tenant" if own_rbac is not None else "platform",
            "mail_source": "tenant" if own_mail else "platform",
            "sealed_secrets": sealed,
            "platform_sealed_secrets": {} if own_mail else await self._platform_sealed(),
            "maintenance": await self._open_maintenance(tenant.id),
        }

    async def _platform_sealed(self) -> dict[str, str]:
        rows = (await self.session.execute(select(PlatformSealedSecret))).scalars()
        return {row.name: row.ciphertext for row in rows}

    async def _sealed(self, tenant_id: UUID) -> dict[str, str]:
        rows = (
            await self.session.execute(
                select(TenantSealedSecret).where(TenantSealedSecret.tenant_id == tenant_id)
            )
        ).scalars()
        return {row.name: row.ciphertext for row in rows}

    async def _open_maintenance(self, tenant_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(TenantMaintenanceRequest)
                .where(TenantMaintenanceRequest.tenant_id == tenant_id)
                .where(TenantMaintenanceRequest.state == MaintenanceState.requested)
                .order_by(TenantMaintenanceRequest.requested_at)
            )
        ).scalars()
        return [
            {
                "id": str(row.id),
                "action": row.action.value,
                "requested_by": row.requested_by,
                "reason": row.reason,
                "params": dict(row.params or {}),
            }
            for row in rows
        ]


__all__ = [
    "POLICY_KEYS",
    "RETIRED_KEYS",
    "SECRET_LOOKING",
    "SECRET_LOOKING_EXEMPT",
    "SettingsError",
    "SettingsService",
    "effective",
    "strip_retired",
    "validate_policy",
    "validate_rbac",
]
