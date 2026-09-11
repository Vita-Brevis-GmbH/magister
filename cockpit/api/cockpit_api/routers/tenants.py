"""Kunden erfassen, ansehen, sperren, entsperren, wiederaufnehmen (ADR-0013 D2).

Der Erfassungs-Endpunkt legt den Kunden an **und** startet den
Bereitstellungs-Auftrag. Scheitert der Auftrag, gibt es trotzdem eine Antwort
mit 202 und dem Protokoll: der Kunde existiert, ist aber auf ``provisioning``
und damit nicht erreichbar. Genau das ist die Zusage — nie halb angelegt.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import Caller, require_bootstrap_token, require_person
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import (
    STEP_ORDER,
    JobStatus,
    ProvisioningJob,
    Tenant,
    TenantStatus,
)
from cockpit_api.schemas.tenant import (
    ProvisioningJobOut,
    SchemaVersionReport,
    TenantCreate,
    TenantLimitsUpdate,
    TenantOut,
    TenantProvisionResult,
    TenantRegistryEntry,
    TenantRelocate,
    TenantSuspend,
)
from cockpit_api.services.provisioning import (
    JobSecrets,
    ProvisioningError,
    TenantProvisioner,
    admin_engine,
    run_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants", tags=["tenants"], dependencies=[Depends(require_bootstrap_token)]
)


def _next_step(job: ProvisioningJob) -> str | None:
    if job.status is JobStatus.succeeded:
        return None
    if job.last_completed_step is None:
        return STEP_ORDER[0].value
    index = STEP_ORDER.index(job.last_completed_step) + 1
    return STEP_ORDER[index].value if index < len(STEP_ORDER) else None


def _result(
    tenant: Tenant, job: ProvisioningJob, secrets: JobSecrets | None
) -> TenantProvisionResult:
    found = secrets or JobSecrets()
    return TenantProvisionResult(
        tenant=TenantOut.model_validate(tenant),
        job=ProvisioningJobOut.model_validate(job),
        role_password=found.role_password,
        data_key=found.data_key,
        next_step=_next_step(job),
    )


async def _load(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


async def _latest_job(session: AsyncSession, tenant_id: UUID) -> ProvisioningJob | None:
    stmt = (
        select(ProvisioningJob)
        .where(ProvisioningJob.tenant_id == tenant_id)
        .order_by(ProvisioningJob.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=list[TenantOut])
async def list_tenants(session: AsyncSession = Depends(get_session)) -> list[Tenant]:
    result = await session.execute(select(Tenant).order_by(Tenant.slug))
    return list(result.scalars())


@router.get("/registry", response_model=list[TenantRegistryEntry])
async def tenant_registry(session: AsyncSession = Depends(get_session)) -> list[Tenant]:
    """Die Registry für die Datenebene — ohne DSN, nur mit Verweis.

    Die Datenebene holt diese Liste beim Start und danach im Hintergrund und
    hält sie im Speicher. Kein Kunden-Request liest je die Konsolen-Datenbank
    (ADR-0013 D4), und ein Ausfall der Konsole lässt jeden Kunden weiterlaufen.

    Gesperrte und in Bereitstellung befindliche Kunden stehen mit drin: die
    Datenebene muss sie kennen, um mit 503 statt 404 zu antworten. Der
    Unterschied ist für den Kunden wichtig — „gibt es nicht" und „gerade nicht
    erreichbar" sind verschiedene Auskünfte.
    """
    result = await session.execute(select(Tenant).order_by(Tenant.slug))
    return list(result.scalars())


@router.post("", response_model=TenantProvisionResult, status_code=status.HTTP_202_ACCEPTED)
async def create_tenant(
    payload: TenantCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TenantProvisionResult:
    tenant = Tenant(
        slug=payload.slug,
        name=payload.name,
        hostname=payload.hostname,
        customer_no=payload.customer_no,
        profile=payload.profile,
        isolation_mode=payload.isolation_mode,
        schema_name=f"t_{payload.slug}",
        db_role=f"r_{payload.slug}",
        dsn_ref=settings.dsn_ref_template.format(slug=payload.slug),
        status=TenantStatus.provisioning,
    )
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "slug, hostname, schema or role already in use"
        ) from exc

    job = ProvisioningJob(tenant_id=tenant.id)
    session.add(job)
    await session.flush()

    result = await _execute(session, tenant, job)
    if job.status is JobStatus.succeeded:
        response.status_code = status.HTTP_201_CREATED
    return result


@router.get("/{tenant_id}", response_model=TenantProvisionResult)
async def get_tenant(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> TenantProvisionResult:
    tenant = await _load(session, tenant_id)
    job = await _latest_job(session, tenant_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no provisioning job for this tenant")
    # Kein Passwort: es gibt es nur im Lauf, in dem es entsteht.
    return _result(tenant, job, None)


@router.post("/{tenant_id}/provisioning/resume", response_model=TenantProvisionResult)
async def resume_provisioning(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> TenantProvisionResult:
    """Abgebrochenen Auftrag ab der Abbruchstelle weiterführen.

    Nicht von vorn: die erledigten Schritte bleiben erledigt. Die Schritte
    sind trotzdem alle idempotent, damit ein Wiederaufnehmen nicht daran
    scheitert, dass die Rolle schon existiert.
    """
    tenant = await _load(session, tenant_id)
    job = await _latest_job(session, tenant_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no provisioning job for this tenant")
    if job.status is JobStatus.succeeded:
        raise HTTPException(status.HTTP_409_CONFLICT, "provisioning already finished")
    return await _execute(session, tenant, job)


@router.post("/{tenant_id}/suspend", response_model=TenantOut)
async def suspend_tenant(
    tenant_id: UUID, payload: TenantSuspend, session: AsyncSession = Depends(get_session)
) -> Tenant:
    """Kunden sperren. Die Datenebene bedient ihn danach mit 503.

    Bewusst kein Eingriff in der Datenbank: die Rolle bleibt, das Schema
    bleibt, die Daten bleiben. Sperren ist eine Aussage über die Bedienung,
    keine über den Bestand — sonst wäre Entsperren eine Wiederherstellung.
    """
    tenant = await _load(session, tenant_id)
    if tenant.status is TenantStatus.provisioning:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "tenant is still provisioning and therefore already unreachable",
        )
    tenant.status = TenantStatus.suspended
    tenant.suspended_at = datetime.now(UTC)
    tenant.suspended_reason = payload.reason
    await _commit_and_refresh(session, tenant)
    logger.info("Kunde %s gesperrt", tenant.slug)
    return tenant


@router.post("/{tenant_id}/unsuspend", response_model=TenantOut)
async def unsuspend_tenant(tenant_id: UUID, session: AsyncSession = Depends(get_session)) -> Tenant:
    tenant = await _load(session, tenant_id)
    if tenant.status is not TenantStatus.suspended:
        raise HTTPException(status.HTTP_409_CONFLICT, "tenant is not suspended")
    tenant.status = TenantStatus.active
    tenant.suspended_at = None
    tenant.suspended_reason = None
    await _commit_and_refresh(session, tenant)
    logger.info("Kunde %s entsperrt", tenant.slug)
    return tenant


@router.post("/{tenant_id}/rotate-role-password", response_model=TenantProvisionResult)
async def rotate_role_password(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> TenantProvisionResult:
    """Neues Passwort für die Mandantenrolle, genau einmal ausgegeben.

    Nötig, weil die Konsole das Passwort nicht speichert. Nach dem Drehen muss
    der Geheimnisspeicher der Datenebene nachgezogen werden, sonst verliert der
    Kunde die Verbindung — der Grund, warum dieser Endpunkt laut ist und nicht
    nebenbei passiert.
    """
    tenant = await _load(session, tenant_id)
    job = await _latest_job(session, tenant_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no provisioning job for this tenant")
    engine = admin_engine()
    try:
        rotated = await TenantProvisioner(
            engine, extension_schema=settings.tenant_extension_schema
        ).rotate_role_password(tenant)
    except ProvisioningError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    finally:
        await engine.dispose()
    await session.commit()
    return _result(tenant, job, JobSecrets(role_password=rotated))


async def _execute(
    session: AsyncSession, tenant: Tenant, job: ProvisioningJob
) -> TenantProvisionResult:
    """Auftrag fahren, festschreiben, dann antworten.

    Die Reihenfolge ist wichtig: ``created_at``/``updated_at`` kommen aus
    Server-Vorgaben und stehen erst nach dem Commit samt ``refresh`` in den
    Objekten. Vor dem Commit zu serialisieren liefert ``None`` — und das fällt
    erst bei der Pydantic-Prüfung auf.
    """
    try:
        engine = admin_engine()
    except ProvisioningError as exc:
        # Kein Verwaltungszugang konfiguriert: der Kunde bleibt angelegt, aber
        # auf provisioning. Das ist eine Konfigurationslücke des Betreibers und
        # gehört sichtbar in den Auftrag, nicht in einen 500er.
        job.status = JobStatus.failed
        job.last_error = str(exc)
        return await _commit_and_serialize(session, tenant, job, None)
    try:
        job, secrets = await run_job(
            session,
            tenant,
            job,
            provisioner=TenantProvisioner(
                engine, extension_schema=settings.tenant_extension_schema
            ),
        )
    finally:
        await engine.dispose()
    return await _commit_and_serialize(session, tenant, job, secrets)


async def _commit_and_refresh(session: AsyncSession, tenant: Tenant) -> None:
    """Festschreiben und die Zeile neu laden.

    ``updated_at`` hat ``onupdate=func.now()``. Nach dem UPDATE ist genau
    dieses Attribut abgelaufen — unabhängig von ``expire_on_commit`` — und ein
    Nachladen beim Serialisieren fällt ausserhalb des Async-Kontexts in
    ``MissingGreenlet``. Also hier laden, nicht dort.
    """
    await session.commit()
    await session.refresh(tenant)


async def _commit_and_serialize(
    session: AsyncSession, tenant: Tenant, job: ProvisioningJob, secrets: JobSecrets | None
) -> TenantProvisionResult:
    await session.commit()
    await session.refresh(tenant)
    await session.refresh(job)
    return _result(tenant, job, secrets)


@router.post("/{tenant_id}/schema-version", response_model=TenantOut)
async def report_schema_version(
    tenant_id: UUID,
    body: SchemaVersionReport,
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    """Den echten Schemastand annehmen (ADR-0021 D2).

    Der einzige Rückkanal von der Datenebene in die Konsole. Er existiert,
    weil die Konsole diese Angabe nicht selbst beschaffen kann: sie hat keinen
    Datenbankzugang zum Kunden, und `schema_version` trug bis hierher nur
    ihre eigene **Erwartung** aus `COCKPIT_EXPECTED_SCHEMA_VERSION`. Nach
    dieser Meldung trägt sie eine Messung.

    Kein `require_person`: es meldet ein Dienst, und der ist keine Person
    (ADR-0020 D4). Was hier ankommt, ist auch kein `actor` — nur eine
    Revision.

    Idempotent: dieselbe Revision zweimal gemeldet aktualisiert nur den
    Zeitstempel. Ein Protokoll-Eintrag entsteht nur bei einer **Änderung**,
    damit ein Fünf-Minuten-Melder nicht das Log füllt.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    previous = tenant.schema_version
    tenant.schema_version = body.head_revision
    tenant.schema_version_reported_at = datetime.now(UTC)
    if previous != body.head_revision:
        logger.info(
            "Kunde %s meldet Schemastand %s (vorher %s).",
            tenant.slug,
            body.head_revision,
            previous or "unbekannt",
        )
        if settings.expected_schema_version and (
            body.head_revision != settings.expected_schema_version
        ):
            # Sichtbar machen, nicht abweisen: die Meldung ist eine Messung,
            # und eine Messung, die nicht zur Erwartung passt, ist eine
            # Auskunft und kein Fehler. Wer sie abwiese, hätte statt der
            # Abweichung wieder nur die Erwartung in der Spalte.
            logger.warning(
                "Kunde %s steht auf %s, erwartet ist %s — Abweichung.",
                tenant.slug,
                body.head_revision,
                settings.expected_schema_version,
            )
    await session.commit()
    await session.refresh(tenant)
    return tenant


@router.put("/{tenant_id}/limits", response_model=TenantOut)
async def update_limits(
    tenant_id: UUID,
    body: TenantLimitsUpdate,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    """Die drei Lastgrenzen setzen — in der Zeile **und** an der Rolle (ADR-0021 D3).

    Beides oder keines: eine Zeile, die eine Grenze behauptet, die in Postgres
    nicht gilt, ist schlechter als keine Angabe. Scheitert das `ALTER ROLE`
    (kein Verwaltungszugang, Rolle noch nicht angelegt), wird die Änderung
    **nicht** gespeichert und die Antwort sagt warum.

    `require_person`: eine Grenze zu heben ist eine Entscheidung, und sie
    gehört zu einem Namen (ADR-0020 D4).
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    # Slug und Vorwerte JETZT lesen. Nach einem `rollback()` sind die
    # Attribute abgelaufen, und der nächste Zugriff wäre ein Nachladen —
    # also IO, mitten in einem synchronen Logger-Aufruf. Das endet in einem
    # `MissingGreenlet` und damit in einem 500 statt der ehrlichen Antwort.
    slug = tenant.slug
    previous = (
        tenant.statement_timeout_ms,
        tenant.idle_in_transaction_ms,
        tenant.connection_limit,
    )
    tenant.statement_timeout_ms = body.statement_timeout_ms
    tenant.idle_in_transaction_ms = body.idle_in_transaction_ms
    tenant.connection_limit = body.connection_limit
    # `admin_engine()` MIT im try: ohne Verwaltungszugang wirft schon der
    # Aufbau, und das ist derselbe Fall — die Grenze liess sich nicht setzen.
    # Stand er aussen, käme ein 500 statt eines 503 mit Begründung.
    try:
        engine = admin_engine()
        try:
            await TenantProvisioner(engine).apply_limits(tenant)
        finally:
            await engine.dispose()
    except Exception as exc:
        await session.rollback()
        logger.warning("Grenzen für %s nicht gesetzt: %s", slug, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Die Grenzen liessen sich in der Datenbank nicht setzen; nichts geändert.",
        ) from exc
    await session.commit()
    await session.refresh(tenant)
    logger.info(
        "Grenzen für %s geändert von %s auf (%d, %d, %d) durch %s: %s",
        slug,
        previous,
        body.statement_timeout_ms,
        body.idle_in_transaction_ms,
        body.connection_limit,
        caller.actor,
        body.reason,
    )
    return tenant


@router.post("/{tenant_id}/relocate", response_model=TenantOut)
async def relocate_tenant(
    tenant_id: UUID,
    body: TenantRelocate,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    """Den Verweis auf die Ablage ändern — der Umzug in einem Schritt (ADR-0021 D5).

    **Nur bei gesperrtem Kunden.** Ein Umzug ist ein Wartungsfenster: Sperren,
    sichern, im Ziel einspielen, umstellen, prüfen, entsperren. Würde diese
    Route auch einen aktiven Kunden umstellen, zeigte die Registry auf eine
    Datenbank, in der die Daten noch nicht sind — und die Datenebene bediente
    ihn aus einem halb gefüllten Schema.

    Der **gemeldete Schemastand wird gelöscht**, nicht übernommen: er war eine
    Messung an der alten Ablage. Die nächste Meldung der Datenebene
    (ADR-0021 D2) ist damit der Beleg, dass der Umzug angekommen ist — bis
    dahin steht in der Konsole ehrlich „nie gemeldet“.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    if tenant.status is not TenantStatus.suspended:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ein Umzug verlangt einen gesperrten Kunden. Erst sperren, dann "
            "sichern, dann umstellen (ADR-0021 D5).",
        )
    previous_ref = tenant.dsn_ref
    previous_mode = tenant.isolation_mode
    if body.dsn_ref == previous_ref and body.isolation_mode is previous_mode:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verweis und Stufe sind unverändert.")
    tenant.dsn_ref = body.dsn_ref
    tenant.isolation_mode = body.isolation_mode
    tenant.schema_version = None
    tenant.schema_version_reported_at = None
    slug = tenant.slug
    await session.commit()
    await session.refresh(tenant)
    logger.warning(
        "Kunde %s umgezogen: Verweis %s -> %s, Stufe %s -> %s, durch %s: %s. "
        "Der gemeldete Schemastand ist gelöscht; die Datenebene muss ihn neu melden.",
        slug,
        previous_ref,
        body.dsn_ref,
        previous_mode.value,
        body.isolation_mode.value,
        caller.actor,
        body.reason,
    )
    return tenant
