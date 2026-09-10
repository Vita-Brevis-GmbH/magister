"""Soll-Zustand der Konsole ins Kundenschema materialisieren (ADR-0017 D3/D4).

Was hier passiert, ist ein **Abgleich** und kein Schreiben: gelesen wird, was
gilt, verglichen mit dem, was gelten soll, und geschrieben wird nur die
Differenz.

Der Grund ist ADR-0017 D4. `AppSettingsService.update()` erhöht bei **jedem**
Aufruf die Version und schreibt **immer** ein Audit-Ereignis — richtig für
einen Menschen am Formular, falsch für eine Schleife, die alle fünf Minuten
läuft. Ohne den Vergleich hier wäre die Versionsnummer nach einem Monat
achttausend und das Audit-Protokoll voll mit `app_settings_updated`. Das ist
nicht Nachvollziehbarkeit, das ist ihr Gegenteil.

Zwei Grenzen, die der Reconciler nicht überschreitet:

* **Keine Geheimnisse** (ADR-0017 D2). Der Soll-Zustand enthält keine, und
  dieser Code würde sie auch nicht schreiben: er baut den Payload aus einer
  Allowlist.
* **Keine Plattform-Capabilities an Kundenrollen** (ADR-0017 D5). Die Prüfung
  liegt im RBAC-Dienst, nicht hier — sie muss auch für ein CLI gelten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.capabilities import Capability
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.schemas.app_settings import AppSettingsUpdate
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.rbac import RbacService, RoleImmutableError, RoleNotFoundError
from magister_api.tenancy.desired_state import DesiredState

logger = logging.getLogger(__name__)

#: Der Akteur, unter dem der Abgleich im Audit erscheint. Ein Name und keine
#: leere Spalte: wer im Protokoll des Kunden liest, soll sehen, dass die
#: Änderung von der Plattform kam und nicht von einer Person im Haus.
RECONCILER_ACTOR = "platform-reconciler@vitabrevis.ch"

#: Die Felder, die der Abgleich schreiben darf. Dieselben Namen wie in der
#: Konsole (`cockpit_api.services.settings.POLICY_KEYS`) — bewusst identisch,
#: damit hier nicht übersetzt werden muss.
#:
#: Was nicht in dieser Liste steht, wird **verworfen und protokolliert**: eine
#: Konsole, die ein unbekanntes Feld schickt, ist entweder neuer als diese
#: Datenebene oder falsch konfiguriert. Beides ist eine Meldung wert und kein
#: Grund, etwas Unbekanntes ins Kundenschema zu schreiben.
RECONCILABLE: frozenset[str] = frozenset(
    {
        "oidc_issuer",
        "oidc_client_id",
        "oidc_redirect_uri",
        "oidc_scopes",
        "bootstrap_admins",
        "mail_domains",
        "ad_dcs",
        "ad_bind_mode",
        "ad_bind_dn",
        "ad_tls_verify",
        "ad_tls_ca_pem",
        "ad_users_search_base",
        "ad_computers_search_base",
        "ad_groups_search_base",
        "ad_sync_interval_minutes",
        "ad_ou_students_other",
        "ad_ou_teachers",
        "ad_groups_teacher",
        "password_store_enabled",
        "instance_profile",
        "module_overrides",
        "ninja_enabled",
        "ninja_region",
        "ninja_client_id",
        "web_tls_cert_pem",
    }
)


@dataclass
class ReconcileResult:
    """Was der Abgleich getan hat. Für den Log und für die Tests."""

    changed_settings: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    changed_roles: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)
    unknown_keys: list[str] = field(default_factory=list)
    unknown_capabilities: list[str] = field(default_factory=list)
    skipped_roles: dict[str, str] = field(default_factory=dict)

    @property
    def touched(self) -> bool:
        return bool(self.changed_settings or self.changed_roles)


#: Listenfelder, deren **Reihenfolge Bedeutung hat**. `ad_dcs` ist die
#: Vorrangliste, in der der ServerPool die Domänencontroller anspricht;
#: `oidc_scopes` geht so an den Anbieter, wie sie dasteht. Bei allen anderen
#: Listen ist die Reihenfolge Zufall — und würde sie mitverglichen, schriebe
#: der Abgleich bei jedem Lauf, weil Postgres eine Liste in der Reihenfolge
#: zurückgibt, in der sie gespeichert wurde, und die Konsole in der, in der
#: sie getippt wurde.
ORDER_MATTERS = frozenset({"ad_dcs", "oidc_scopes"})


def settings_diff(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Feldweise: {feld: (alt, neu)} für alles, was wirklich abweicht."""
    diff: dict[str, tuple[Any, Any]] = {}
    for key, want in desired.items():
        have = current.get(key)
        if isinstance(have, list) and isinstance(want, list) and key not in ORDER_MATTERS:
            differs = sorted(map(str, have)) != sorted(map(str, want))
        else:
            differs = have != want
        if differs:
            diff[key] = (have, want)
    return diff


class Reconciler:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _current_settings(self) -> dict[str, Any]:
        """Der geltende Stand, auf die abgleichbaren Felder beschränkt.

        Ausdrücklich diese Spalten und nicht die ganze Zeile. Zwei Gründe, und
        der zweite ist der wichtige:

        * Die API-Ansicht (`get_redacted_for_api`) taugt nicht: sie redigiert
          Geheimnisse und liefert `*_set`-Flags, mit denen sich nichts
          vergleichen lässt.
        * Die ganze ORM-Zeile taugt auch nicht: sie trägt die
          `*_enc`-Spalten mit. Ein Abgleich, der sie in der Hand hält, ist
          einer, der sie eines Tages irgendwohin schreibt.

        `# scope-bypass: app_settings ist ein Singleton je Kundenschema, ohne
        Schul-Scope. Die Mandantentrennung leistet der ``search_path`` dieser
        Sitzung.`
        """
        columns = [getattr(AppSettings, key) for key in sorted(RECONCILABLE)]
        stmt = select(*columns).where(AppSettings.id == 1)
        row = (await self.session.execute(stmt)).one()
        return dict(zip(sorted(RECONCILABLE), row, strict=True))

    async def reconcile(
        self, desired: DesiredState, *, tenant_slug: str, dry_run: bool = False
    ) -> ReconcileResult:
        result = ReconcileResult()

        wanted: dict[str, Any] = {}
        for key, value in desired.settings.items():
            if key not in RECONCILABLE:
                result.unknown_keys.append(key)
                continue
            if value is None:
                # Kann aus der Konsole nicht kommen (`effective()` lässt ein
                # `null` als „Vorgabe gilt" weg), und wenn doch, dann still:
                # `AppSettingsUpdate` liest `None` als „nicht anfassen". Ein
                # Feld zu LEEREN heisst leerer String beziehungsweise leere
                # Liste — dieselbe Bedeutung wie am Formular.
                continue
            wanted[key] = value

        current = await self._current_settings()
        result.changed_settings = settings_diff(current, wanted)

        if result.unknown_keys:
            # WARNING und nicht ERROR: der Betrieb läuft weiter, mit dem Rest.
            logger.warning(
                "Soll-Zustand für %s enthält unbekannte Felder, die nicht "
                "materialisiert werden: %s. Ist die Konsole neuer als diese "
                "Datenebene?",
                tenant_slug,
                ", ".join(sorted(result.unknown_keys)),
            )

        if result.changed_settings and not dry_run:
            await self._apply_settings(result.changed_settings, tenant_slug=tenant_slug)

        if desired.has_rbac:
            await self._reconcile_rbac(
                desired.rbac, result, tenant_slug=tenant_slug, dry_run=dry_run
            )

        if result.touched:
            logger.info(
                "Soll-Zustand für %s materialisiert: %d Einstellung(en), %d Rolle(n)",
                tenant_slug,
                len(result.changed_settings),
                len(result.changed_roles),
            )
        return result

    async def _apply_settings(self, diff: dict[str, tuple[Any, Any]], *, tenant_slug: str) -> None:
        """Nur die geänderten Felder schreiben.

        Über `AppSettingsUpdate` und `AppSettingsService.update()`, damit es
        **einen** Schreibweg gibt: dort sitzen die Validierung, die
        Versionszählung und das Audit-Ereignis. Ein zweiter Weg wäre einer, der
        beim nächsten Umbau vergessen wird.
        """
        payload = AppSettingsUpdate(**{key: new for key, (_, new) in diff.items()})
        await AppSettingsService(self.session, self.settings).update(
            payload,
            actor_upn=RECONCILER_ACTOR,
            actor_object_guid=None,
            ip=None,
            request_id=f"reconcile:{tenant_slug}",
            action="platform_settings_reconciled",
        )

    async def _reconcile_rbac(
        self,
        desired: dict[str, list[str]],
        result: ReconcileResult,
        *,
        tenant_slug: str,
        dry_run: bool,
    ) -> None:
        """Die Rechte-Matrix abgleichen — nur die vorgegebenen Rollen.

        Rollen, die die Vorgabe nicht nennt, bleiben **unberührt**. Eine
        Vorgabe ist eine Aussage über die genannten Rollen und nicht über alle:
        sonst löschte eine Vorgabe mit zwei Rollen die eigenen Rollen des
        Kunden mit, und niemand hätte das gemeint.
        """
        svc = RbacService(self.session)
        have = await svc.capabilities_by_role()
        known = {c.value for c in Capability}

        for role_key, caps in desired.items():
            unknown = [c for c in caps if c not in known]
            if unknown:
                # Nicht das Ganze verwerfen: die bekannten Rechte werden
                # gesetzt, die unbekannten gemeldet. Eine Konsole, die eine
                # neuere Capability kennt, soll den Rest nicht blockieren.
                result.unknown_capabilities.extend(unknown)
                caps = [c for c in caps if c in known]
            before = sorted(have.get(role_key, []))
            after = sorted(dict.fromkeys(caps))
            if before == after:
                continue
            if dry_run:
                result.changed_roles[role_key] = (before, after)
                continue
            try:
                await svc.set_capabilities(role_key, [Capability(c) for c in after])
            except RoleNotFoundError:
                # Eine Rolle, die es beim Kunden nicht gibt, wird **nicht**
                # angelegt. Rollen anzulegen ist eine Aussage über die
                # Organisation des Kunden; eine Rechte-Vorgabe ist es nicht.
                result.skipped_roles[role_key] = "Rolle existiert bei diesem Kunden nicht"
                continue
            except RoleImmutableError as exc:
                # `admin` hält implizit alles, abgeleitete Rollen halten keine
                # groben Rechte — beides ist eine Invariante der Datenebene und
                # keine, die die Konsole aufheben darf.
                result.skipped_roles[role_key] = str(exc)
                continue
            result.changed_roles[role_key] = (before, after)

        if result.unknown_capabilities:
            logger.warning(
                "Soll-Zustand für %s nennt unbekannte Rechte: %s",
                tenant_slug,
                ", ".join(sorted(set(result.unknown_capabilities))),
            )
        if result.skipped_roles:
            logger.warning(
                "Rechte-Vorgabe für %s übersprungen: %s",
                tenant_slug,
                "; ".join(f"{k}: {v}" for k, v in sorted(result.skipped_roles.items())),
            )

        if result.changed_roles and not dry_run:
            await AuditService(self.session, self.settings).emit(
                action="platform_rbac_reconciled",
                target_kind="rbac",
                target_id="matrix",
                actor_upn=RECONCILER_ACTOR,
                actor_object_guid=None,
                school_id=None,
                ip=None,
                request_id=f"reconcile:{tenant_slug}",
                payload={
                    role: {"before": before, "after": after}
                    for role, (before, after) in result.changed_roles.items()
                },
            )


__all__ = ["RECONCILABLE", "RECONCILER_ACTOR", "Reconciler", "ReconcileResult", "settings_diff"]
