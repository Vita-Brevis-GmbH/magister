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

* **Keine Geheimnisse im Klartext** (ADR-0017 D2). Der Soll-Zustand enthält
  keine; die Einstellungen kommen aus einer Allowlist. Die einzige Ausnahme
  sind **versiegelte** Geheimnisse (ADR-0024 D3): die Konsole kann sie nicht
  lesen, geöffnet werden sie erst hier, mit dem Schlüssel dieses Kunden.
* **Keine Plattform-Capabilities an Kundenrollen** (ADR-0017 D5). Die Prüfung
  liegt im RBAC-Dienst, nicht hier — sie muss auch für ein CLI gelten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.capabilities import Capability
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.models.base import utcnow
from magister_api.models.platform_template import PlatformDocumentTemplate
from magister_api.schemas.app_settings import AppSettingsUpdate
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.demo_data import DemoDataService
from magister_api.services.document_templates import (
    DocumentTemplateService,
    TemplateRenderError,
    sample_context,
)
from magister_api.services.imports import purge_import_history
from magister_api.services.rbac import (
    PlatformCapabilityError,
    RbacService,
    RoleImmutableError,
    RoleNotFoundError,
)
from magister_api.tenancy.desired_state import (
    MAINTENANCE_ACTIONS,
    DesiredMaintenance,
    DesiredState,
    DesiredTemplate,
)
from magister_api.tenancy.keys import keys_for
from magister_api.tenancy.sealing import SEALABLE, UnsealError, unseal

logger = logging.getLogger(__name__)

#: Der Akteur, unter dem der Abgleich im Audit erscheint. Ein Name und keine
#: leere Spalte: wer im Protokoll des Kunden liest, soll sehen, dass die
#: Änderung von der Plattform kam und nicht von einer Person im Haus.
RECONCILER_ACTOR = "platform-reconciler@vitabrevis.ch"

#: Das Audit-Ereignis, das die Ausführung eines Wartungsauftrags belegt. Sein
#: Ziel ist die Auftrags-Id — daran erkennt der nächste Lauf „schon erledigt".
MAINTENANCE_EVENT = "platform_maintenance_executed"

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

#: Die zwei Felder, die nicht über `AppSettingsUpdate` geschrieben werden,
#: sondern über `AppSettingsService.set_module_settings`.
MODULE_KEYS: frozenset[str] = frozenset({"instance_profile", "module_overrides"})


@dataclass
class ReconcileResult:
    """Was der Abgleich getan hat. Für den Log und für die Tests."""

    changed_settings: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    changed_roles: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)
    unknown_keys: list[str] = field(default_factory=list)
    unknown_capabilities: list[str] = field(default_factory=list)
    skipped_roles: dict[str, str] = field(default_factory=dict)
    #: „key/language" der Vorlagen, die neu hereinkamen, sich geändert haben
    #: oder verschwunden sind. Drei Listen und nicht eine Zahl: im Audit des
    #: Kunden soll stehen, *was* sich geändert hat.
    added_templates: list[str] = field(default_factory=list)
    updated_templates: list[str] = field(default_factory=list)
    removed_templates: list[str] = field(default_factory=list)
    #: Vorlagen, die sich nicht rendern liessen und deshalb **nicht**
    #: materialisiert wurden: {key/language: Grund}.
    rejected_templates: dict[str, str] = field(default_factory=dict)

    #: Versiegelte Geheimnisse, die neu ins Kundenschema geschrieben wurden.
    changed_secrets: list[str] = field(default_factory=list)
    #: {name: Grund} — ließ sich nicht öffnen oder ist nicht versiegelbar.
    rejected_secrets: dict[str, str] = field(default_factory=dict)
    #: Ergebnisse der Wartungsaufträge, für die Zustandsmeldung an die Konsole.
    maintenance_results: list[dict[str, Any]] = field(default_factory=list)
    #: Ob in diesem Lauf ein Wartungsauftrag tatsächlich ausgeführt wurde.
    maintenance_executed: bool = False

    @property
    def changed_templates(self) -> bool:
        return bool(self.added_templates or self.updated_templates or self.removed_templates)

    @property
    def touched(self) -> bool:
        return bool(
            self.changed_settings
            or self.changed_roles
            or self.changed_templates
            or self.changed_secrets
            or self.maintenance_executed
        )


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


def _flat(result: dict[str, Any]) -> dict[str, int | str]:
    """Ein Wartungsergebnis meldefähig machen: nur Zahlen und kurze Texte."""
    out: dict[str, int | str] = {}
    for key, value in result.items():
        if isinstance(value, bool | int):
            out[key] = int(value)
        elif isinstance(value, str):
            out[key] = value[:200]
    return out


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
        self,
        desired: DesiredState,
        *,
        tenant_slug: str,
        dry_run: bool = False,
        tenant_ref: str | None = None,
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

        if desired.templates is not None:
            await self._reconcile_templates(
                desired.templates, result, tenant_slug=tenant_slug, dry_run=dry_run
            )

        if desired.sealed_secrets and tenant_ref and not dry_run:
            await self._reconcile_sealed(
                desired.sealed_secrets, result, tenant_ref=tenant_ref, tenant_slug=tenant_slug
            )

        if desired.maintenance and not dry_run:
            for request in desired.maintenance:
                await self._run_maintenance(request, result, tenant_slug=tenant_slug)

        if result.touched:
            logger.info(
                "Soll-Zustand für %s materialisiert: %d Einstellung(en), %d Rolle(n), "
                "%d Vorlage(n)",
                tenant_slug,
                len(result.changed_settings),
                len(result.changed_roles),
                len(result.added_templates)
                + len(result.updated_templates)
                + len(result.removed_templates),
            )
        return result

    async def _reconcile_templates(
        self,
        desired: tuple[DesiredTemplate, ...],
        result: ReconcileResult,
        *,
        tenant_slug: str,
        dry_run: bool,
    ) -> None:
        """Die Plattformvorlagen abgleichen (ADR-0018 D1, D6).

        Geschrieben wird **nur** in `platform_document_templates`. Die eigenen
        Vorlagen des Kunden (`document_templates`) werden hier nicht gelesen
        und nicht angefasst — das ist der Sinn der zweiten Tabelle (D2), und
        deshalb kann ein Rollout einen gewachsenen Elternbrief nicht
        überfahren.

        Die gelieferte Liste ist vollständig: was nicht darin steht,
        verschwindet. Dass „nichts geliefert" von „keine Vorlagen" zu
        unterscheiden ist, hat der Abholer bereits entschieden — hier kommt
        eine Liste an oder diese Methode wird nicht gerufen.

        `# scope-bypass: Plattformvorlagen gelten für den ganzen Mandanten und
        tragen keine Personendaten. Die Mandantentrennung leistet der
        ``search_path`` dieser Sitzung.`
        """
        rows = (await self.session.execute(select(PlatformDocumentTemplate))).scalars().all()
        have = {(row.key, row.language): row for row in rows}
        want = {(t.key, t.language): t for t in desired}

        for pair, template in want.items():
            label = f"{pair[0]}/{pair[1]}"
            row = have.get(pair)
            if not self._renderable(template, label, result, tenant_slug=tenant_slug):
                continue
            if row is None:
                result.added_templates.append(label)
                if not dry_run:
                    self.session.add(
                        PlatformDocumentTemplate(
                            key=template.key,
                            language=template.language,
                            subject=template.subject,
                            body_html=template.body_html,
                            may_override=template.may_override,
                            version=template.version,
                        )
                    )
                continue
            unchanged = (
                row.version == template.version
                and row.subject == template.subject
                and row.body_html == template.body_html
                and row.may_override == template.may_override
            )
            if unchanged:
                # Der Normalfall. Kein Schreiben, kein Audit-Ereignis, kein
                # neuer `delivered_at` — sonst sähe die Oberfläche bei jedem
                # Lauf eine „neue" Lieferung.
                continue
            result.updated_templates.append(label)
            if dry_run:
                continue
            row.subject = template.subject
            row.body_html = template.body_html
            row.may_override = template.may_override
            row.version = template.version
            row.delivered_at = utcnow()

        gone = sorted(set(have) - set(want))
        # Eine abgewiesene Vorlage gilt nicht als „nicht geliefert": sie steht
        # im Soll-Zustand, sie ist nur unbrauchbar. Ihre bisherige, brauchbare
        # Fassung bleibt deshalb stehen, statt mit ihr zu verschwinden.
        for pair in gone:
            result.removed_templates.append(f"{pair[0]}/{pair[1]}")
            if not dry_run:
                await self.session.execute(
                    delete(PlatformDocumentTemplate).where(
                        PlatformDocumentTemplate.key == pair[0],
                        PlatformDocumentTemplate.language == pair[1],
                    )
                )

        if result.changed_templates and not dry_run:
            await AuditService(self.session, self.settings).emit(
                action="platform_templates_reconciled",
                target_kind="document_template",
                target_id="platform",
                actor_upn=RECONCILER_ACTOR,
                actor_object_guid=None,
                school_id=None,
                ip=None,
                request_id=f"reconcile:{tenant_slug}",
                payload={
                    "added": sorted(result.added_templates),
                    "updated": sorted(result.updated_templates),
                    "removed": sorted(result.removed_templates),
                },
            )

    def _renderable(
        self,
        template: DesiredTemplate,
        label: str,
        result: ReconcileResult,
        *,
        tenant_slug: str,
    ) -> bool:
        """Prüft, ob sich die Vorlage überhaupt rendern lässt.

        Die Konsole kann das nicht: sie kennt den Kontext eines Briefes nicht.
        Ohne diese Prüfung wäre der erste Ort, an dem ein Tippfehler in einem
        Platzhalter auffällt, der **Drucker eines Kunden** — und zwar als
        Fehlerseite statt als Brief. Es ist derselbe Grund, aus dem
        `DocumentTemplateService.save()` beim Speichern rendert.

        Eine abgewiesene Vorlage wird nicht materialisiert; eine bereits
        vorhandene, brauchbare Fassung bleibt stehen. Der Betrieb geht mit dem
        letzten guten Stand weiter — dieselbe Zusage wie beim Ausfall der
        Konsole.

        **Kein Audit-Ereignis.** Der Befund gehört dem Betreiber, nicht dem
        Kunden, und die Konsole liefert die kaputte Vorlage bei jedem Lauf
        wieder: ein Ereignis daraus wäre alle fünf Minuten dasselbe im
        Protokoll des Kunden. Deshalb ERROR in den Log.
        """
        try:
            DocumentTemplateService.render_body(template.body_html, sample_context())
        except TemplateRenderError as exc:
            result.rejected_templates[label] = str(exc)
            logger.error(
                "Plattformvorlage %s für %s liess sich nicht rendern und wurde nicht "
                "übernommen: %s. Der bisherige Stand bleibt in Kraft.",
                label,
                tenant_slug,
                exc,
            )
            return False
        if template.subject:
            try:
                DocumentTemplateService.render_body(template.subject, sample_context())
            except TemplateRenderError as exc:
                result.rejected_templates[label] = f"Betreff: {exc}"
                logger.error(
                    "Betreff der Plattformvorlage %s für %s liess sich nicht rendern: %s",
                    label,
                    tenant_slug,
                    exc,
                )
                return False
        return True

    async def _reconcile_sealed(
        self,
        sealed: dict[str, str],
        result: ReconcileResult,
        *,
        tenant_ref: str,
        tenant_slug: str,
    ) -> None:
        """Versiegelte Geheimnisse öffnen und, wenn sie abweichen, schreiben (ADR-0024 D3).

        Verglichen wird mit dem entschlüsselten geltenden Wert, damit nicht
        jeder Lauf das Geheimnis neu schreibt und ein Audit-Ereignis erzeugt.
        Geschrieben wird über denselben einen Weg wie am Formular
        (`AppSettingsService.update`) — dort wird verschlüsselt, und das
        Audit-Ereignis trägt nur „gedreht", nie den Wert.
        """
        secrets_key = keys_for(self.session, self.settings).secrets_key
        current = await AppSettingsService(self.session, self.settings).get_effective()
        have = {
            "oidc_client_secret": current.oidc_client_secret,
            "ninja_client_secret": current.ninja_client_secret,
        }
        updates: dict[str, str] = {}
        for name, blob in sorted(sealed.items()):
            if name not in SEALABLE:
                result.rejected_secrets[name] = "nicht versiegelbar"
                continue
            try:
                plain = unseal(secrets_key, blob, tenant_ref=tenant_ref, name=name)
            except UnsealError as exc:
                result.rejected_secrets[name] = str(exc)
                logger.warning("Geheimnis %s für %s nicht geöffnet: %s", name, tenant_slug, exc)
                continue
            if plain != have.get(name):
                updates[name] = plain
        if not updates:
            return
        await AppSettingsService(self.session, self.settings).update(
            AppSettingsUpdate(
                oidc_client_secret=updates.get("oidc_client_secret"),
                ninja_client_secret=updates.get("ninja_client_secret"),
            ),
            actor_upn=RECONCILER_ACTOR,
            actor_object_guid=None,
            ip=None,
            request_id=f"reconcile:{tenant_slug}"[:36],
            action="platform_secret_reconciled",
        )
        result.changed_secrets.extend(sorted(updates))

    async def _maintenance_done(self, request_id: str) -> int | None:
        """Id des Ausführungs-Ereignisses zu diesem Auftrag, falls es eines gibt.

        `# scope-bypass: gelesen werden nur Aktion und Ziel eines
        Plattform-Ereignisses, keine Personendaten.`
        """
        stmt = (
            select(func.max(AuditEvent.id))
            .where(AuditEvent.action == MAINTENANCE_EVENT)
            .where(AuditEvent.target_id == request_id)
        )
        found = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(found) if found is not None else None

    async def _run_maintenance(
        self, request: DesiredMaintenance, result: ReconcileResult, *, tenant_slug: str
    ) -> None:
        """Einen Wartungsauftrag genau einmal ausführen (ADR-0024 D4).

        Zwei Container gleichen denselben Kunden ab. Damit derselbe Auftrag
        nicht zweimal läuft, sperrt ein Advisory-Lock auf die Auftrags-Id bis
        zum Ende der Transaktion; geprüft wird danach, ob es das
        Ausführungs-Ereignis schon gibt. Der zweite Container findet es und
        meldet nur noch das Ergebnis.
        """
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"maint:{request.id}"}
        )
        audit = AuditService(self.session, self.settings)
        done = await self._maintenance_done(request.id)
        if done is not None:
            record = await audit.read(done)
            payload = record.payload if record is not None else {}
            result.maintenance_results.append(
                {"id": request.id, "ok": bool(payload.get("ok", True)), "result": _flat(payload)}
            )
            return
        if request.action not in MAINTENANCE_ACTIONS:
            result.maintenance_results.append(
                {"id": request.id, "ok": False, "result": {"error": "unknown_action"}}
            )
            return

        # Im Protokoll des Kunden steht, wer bei Vita Brevis es ausgelöst hat.
        actor = f"vita-brevis:{request.requested_by}"[:320]
        request_id = request.id.replace("-", "")[:36]
        outcome: dict[str, Any]
        if request.action == "demo_purge":
            purged = await DemoDataService(self.session, self.settings).purge(
                actor_upn=actor, actor_object_guid=None, ip=None, request_id=request_id
            )
            outcome = {
                "ok": True,
                "found": int(purged.found),
                "schools": purged.schools,
                "classes": purged.classes,
                "users": purged.users,
            }
        else:  # audit_reset
            imports_deleted = await purge_import_history(self.session)
            deleted = await audit.purge(
                actor_upn=actor,
                actor_object_guid=None,
                ip=None,
                request_id=request_id,
                extra={"imports_deleted": imports_deleted},
            )
            outcome = {"ok": True, "deleted": deleted, "imports_deleted": imports_deleted}

        # Das Ausführungs-Ereignis zuletzt: beim Zurücksetzen des Protokolls
        # muss es die Löschung überleben, und es ist der Beleg für „einmal".
        await audit.emit(
            action=MAINTENANCE_EVENT,
            target_kind="platform_maintenance",
            target_id=request.id,
            actor_upn=actor,
            actor_object_guid=None,
            school_id=None,
            ip=None,
            request_id=request_id,
            payload={**outcome, "action": request.action, "reason": request.reason[:500]},
        )
        result.maintenance_results.append({"id": request.id, "ok": True, "result": _flat(outcome)})
        result.maintenance_executed = True
        logger.info(
            "Wartungsauftrag %s (%s) für %s ausgeführt", request.id, request.action, tenant_slug
        )

    async def _apply_settings(self, diff: dict[str, tuple[Any, Any]], *, tenant_slug: str) -> None:
        """Nur die geänderten Felder schreiben.

        Über `AppSettingsUpdate` und `AppSettingsService.update()`, damit es
        **einen** Schreibweg gibt: dort sitzen die Validierung, die
        Versionszählung und das Audit-Ereignis. Ein zweiter Weg wäre einer, der
        beim nächsten Umbau vergessen wird.
        """
        svc = AppSettingsService(self.session, self.settings)
        request_id = f"reconcile:{tenant_slug}"
        plain = {key: new for key, (_, new) in diff.items() if key not in MODULE_KEYS}
        if plain:
            await svc.update(
                AppSettingsUpdate(**plain),
                actor_upn=RECONCILER_ACTOR,
                actor_object_guid=None,
                ip=None,
                request_id=request_id,
                action="platform_settings_reconciled",
            )
        # Profil und Modul-Schalter haben ihren eigenen Schreibweg. Über
        # `AppSettingsUpdate` gingen sie still verloren: das Schema kennt sie
        # nicht, Pydantic verwirft unbekannte Felder. Der Abgleich sah den
        # Unterschied bei jedem Lauf, schrieb ihn nie, und der Kunde blieb auf
        # „Schule", obwohl die Konsole „Firma" sagte.
        if "instance_profile" in diff or "module_overrides" in diff:
            profile = diff.get("instance_profile", (None, None))[1]
            switches = diff.get("module_overrides", (None, None))[1]
            await svc.set_module_settings(
                instance_profile=str(profile) if profile is not None else None,
                module_overrides=(
                    {str(k): bool(v) for k, v in cast(dict[object, object], switches).items()}
                    if isinstance(switches, dict)
                    else None
                ),
                actor_upn=RECONCILER_ACTOR,
                actor_object_guid=None,
                ip=None,
                request_id=request_id,
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
            except PlatformCapabilityError as exc:
                # Die Konsole hat versucht, ein Plattform-Recht an eine
                # Kundenrolle zu geben (ADR-0017 D5). Das ist kein Tippfehler,
                # den man stillschweigend beheben sollte, sondern ein Befund:
                # er gehört in den Log und die Rolle bleibt, wie sie war.
                logger.error(
                    "Soll-Zustand für %s wollte %s ein Plattform-Recht geben: %s",
                    tenant_slug,
                    role_key,
                    exc,
                )
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
