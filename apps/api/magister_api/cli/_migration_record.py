"""Was nach einer Migration festgehalten wird (ADR-0021 D2).

Zwei Dinge, und beide gehören hierhin und nicht in die Konsole:

1. **Ein Audit-Ereignis im Schema des Kunden.** Die harte Regel verlangt „ein
   kundensichtbares Audit-Ereignis bei jedem Rollout in ein Kundenschema“.
   Die Konsole *kann* es nicht schreiben: `audit_events.payload` ist mit dem
   Kundenschlüssel verschlüsselt, und der liegt ausdrücklich nicht dort
   (ADR-0016 D8). Hier liegt er.
2. **Die Meldung des echten Kopfstands an die Konsole.** Gelesen aus
   `alembic_version` im Kundenschema, nicht aus einer Erwartung. Warum das
   nötig ist, steht in `tenancy/console_report.py`.

Alles hier passiert **nach** der Migration. Scheitert es, ist die Migration
trotzdem gelaufen — deshalb wird nichts davon zum Abbruchgrund, sondern zu
einer benannten Auslassung. Eine geglückte Migration mit unerreichbarer
Konsole darf nicht wie eine gescheiterte aussehen.

Eigene Engine je Mandant, danach weggeworfen: ein CLI, das einmal läuft,
braucht keinen Verbindungs-Pool, und der Prozess-Global aus `tenancy.context`
wäre hier eine Abhängigkeit, die nur der Anfragepfad braucht.
"""

from __future__ import annotations

import getpass
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.tenancy.console_report import (
    ReportRejectedError,
    read_schema_head,
    report_schema_version,
)
from magister_api.tenancy.keys import TenantKeyError, attach_keys, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.scope import apply_tenant_scope

#: Was im Protokoll als Handelnder steht. Kein UPN: es ist kein Mensch, der
#: sich angemeldet hat, und es soll nicht aussehen wie einer. Wer das Werkzeug
#: aufgerufen hat, steht in der Nutzlast.
ROLLOUT_ACTOR = "system:schema-rollout"


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    """Was festgehalten wurde — und was nicht."""

    head: str | None
    audited: bool
    reported: bool
    #: Kurze Begründungen für alles, was nicht geklappt hat. Fürs Terminal.
    notes: tuple[str, ...] = ()


async def read_head(tenant: Tenant, settings: Settings) -> str | None:
    """Kopf-Revision aus dem Schema des Mandanten. ``None`` = nie migriert.

    Läuft **vor** der Migration, damit das Ereignis hinterher sagen kann,
    woher der Kunde kam. Ein Fehler hier ist kein Grund, die Migration zu
    lassen: dann steht im Ereignis „unbekannt“, und das ist ehrlicher als
    keine Migration.
    """
    engine = create_async_engine(tenant.dsn)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
            head = await read_schema_head(session, tenant.schema_name)
            await session.rollback()
            return head
    except Exception:  # noqa: BLE001 — der Aufrufer migriert trotzdem
        return None
    finally:
        await engine.dispose()


async def record_migration(
    tenant: Tenant,
    settings: Settings,
    *,
    before: str | None,
    dump: str | None,
    single_tenant: bool,
) -> RecordOutcome:
    """Ereignis schreiben und Stand melden. Wirft nichts.

    ``before`` ist die Revision vor der Migration, ``dump`` der **Dateiname**
    der Rückfahrkarte — nicht ihr Pfad: wohin der Betreiber seine Dumps legt,
    ist seine Sache und keine Auskunft für den Kunden. Dass es eine gibt, ist
    eine.

    ``single_tenant`` entscheidet, ob die Schlüssel aus den mandantenlosen
    Einstellungen gelten dürfen. Es wird durchgereicht und nicht hier
    geraten: bei mehreren Mandanten wäre ein gemeinsamer Kundenschlüssel der
    Punkt, an dem Crypto-Shredding und die zweite Backup-Schicht unwahr
    werden (ADR-0016 D8).
    """
    notes: list[str] = []
    head: str | None = None
    audited = False

    keys = None
    try:
        keys = resolve_tenant_keys(
            tenant.slug,
            fallback_audit_key=settings.audit_key.get_secret_value(),
            fallback_audit_key_id=settings.audit_key_id,
            fallback_secrets_key=settings.app_secrets_key(),
            single_tenant=single_tenant,
        )
    except TenantKeyError as exc:
        # Ohne Kundenschlüssel kein verschlüsseltes Ereignis. Eine Auslassung,
        # die benannt werden muss — nicht eine, die man stillschweigend
        # hinnimmt.
        notes.append(f"kein Audit-Ereignis: {exc}")

    engine = create_async_engine(tenant.dsn)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            await apply_tenant_scope(session, tenant, extension_schema=settings.extension_schema)
            head = await read_schema_head(session, tenant.schema_name)
            if keys is None:
                await session.rollback()
            else:
                attach_keys(session, keys)
                await AuditService(session, settings).emit(
                    action="schema_migrated",
                    target_kind="tenant_schema",
                    target_id=tenant.schema_name,
                    actor_upn=ROLLOUT_ACTOR,
                    actor_object_guid=None,
                    school_id=None,
                    ip=None,
                    request_id=uuid.uuid4().hex,
                    payload={
                        "from_revision": before or "unbekannt",
                        "to_revision": head or "unbekannt",
                        "dump": dump or "keiner (--no-dump)",
                        "run_by": _who(),
                    },
                )
                await session.commit()
                audited = True
    except Exception as exc:  # noqa: BLE001 — nichts hier darf den Lauf stoppen
        notes.append(f"Protokoll im Kundenschema gescheitert: {exc}")
    finally:
        await engine.dispose()

    reported = False
    if not head:
        notes.append("kein Stand aus alembic_version gelesen — nichts gemeldet")
    elif not settings.console_registry_url:
        # Einzelinstallation: es gibt keine Konsole, der Stand steht im
        # Schema, und damit ist alles gesagt.
        pass
    elif not tenant.console_id:
        notes.append("Mandant aus MAGISTER_TENANTS — die Konsole kennt ihn nicht")
    else:
        try:
            await report_schema_version(
                settings.console_registry_url,
                tenant.console_id,
                head_revision=head,
                token=settings.console_registry_token.get_secret_value(),
                management_marker=settings.console_management_marker.get_secret_value(),
            )
            reported = True
        except ReportRejectedError as exc:
            notes.append(f"Konsole nicht benachrichtigt: {exc}")

    return RecordOutcome(head=head, audited=audited, reported=reported, notes=tuple(notes))


def _who() -> str:
    """Wer das Werkzeug aufgerufen hat, so gut es ohne Anmeldung geht."""
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - kein Benutzername im Container
        return "unbekannt"


__all__ = ["ROLLOUT_ACTOR", "RecordOutcome", "read_head", "record_migration"]
