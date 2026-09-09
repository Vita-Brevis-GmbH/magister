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

from cockpit_api.auth import require_bootstrap_token
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
    TenantCreate,
    TenantOut,
    TenantProvisionResult,
    TenantRegistryEntry,
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
