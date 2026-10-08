"""Der Connector-Kanal (ADR-0014).

Zwei getrennte Oberflächen in einer Datei, weil sie dasselbe Datenmodell
teilen — aber mit **verschiedener** Authentisierung:

- ``/api/tenants/{id}/agents…`` — die Konsole. Operator-Zertifikat plus
  Konsolen-Token, erreichbar nur über den Management-Listener (TCP 4444).
- ``/connector/…`` — der Agent. Client-Zertifikat aus der Plattform-CA plus
  API-Key, erreichbar über den eigenen Listener (TCP 46200). **Kein**
  Konsolen-Token, und der Marker-Riegel der Konsole gilt hier nicht: der
  Connector-Listener ist absichtlich öffentlich, weil der Agent aus dem
  Kundennetz anruft.

Der Agent-Pfad gibt bei jeder Ablehnung dasselbe 401 zurück. Ob Fingerprint
unbekannt, API-Key falsch, Agent widerrufen oder Kunde gesperrt ist, erfährt
der Anrufer nicht — der Grund steht im Log.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import Caller, require_bootstrap_token, require_person
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import (
    AgentStatus,
    ConnectorAgent,
    ConnectorJob,
    JobState,
    Tenant,
    TenantConnectorSettings,
    TenantStatus,
)
from cockpit_api.schemas.connector import (
    AgentAdSettings,
    AgentEnrollRequest,
    AgentEnrollResponse,
    AgentOut,
    AgentRemoteConfig,
    AgentRenewRequest,
    AgentRenewResponse,
    AgentRevoke,
    ConnectorSettingsIn,
    ConnectorSettingsOut,
    EnrollmentCreate,
    EnrollmentOut,
    JobDetailOut,
    JobEnqueue,
    JobForAgent,
    JobOut,
    JobResultIn,
)
from cockpit_api.services import connector as svc
from cockpit_api.services.connector_ca import (
    CertificateIssueError,
    ConnectorCa,
    spki_fingerprint_from_der_base64,
)
from cockpit_api.services.connector_queue import (
    JobNotClaimableError,
    MethodNotAllowedError,
    claim_next,
    enqueue,
    expire_stale_jobs,
    submit_result,
)
from cockpit_api.services.connector_scope import ScopeError, check_scope
from cockpit_api.services.settings import SettingsService

logger = logging.getLogger(__name__)

# --- Konsolenseite ---------------------------------------------------------
console = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["connector"],
    dependencies=[Depends(require_bootstrap_token)],
)

# --- Agentenseite ----------------------------------------------------------
agent_api = APIRouter(prefix="/connector", tags=["connector-agent"])


async def _tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


@console.post("/enrollments", response_model=EnrollmentOut, status_code=201)
async def create_enrollment(
    tenant_id: UUID,
    payload: EnrollmentCreate,
    session: AsyncSession = Depends(get_session),
) -> EnrollmentOut:
    """Einmal-Token für ein Agent-Paket ausstellen.

    Das Paket selbst enthält **kein** Geheimnis ausser diesem Token: Installer,
    CA-Bundle und Token. Wer es abfängt, kann einen Agenten anmelden, solange
    das Token gilt — deshalb 24 Stunden, deshalb einmal einlösbar, und deshalb
    zeigt die Konsole danach den Fingerprint, an dem der Betreiber merkt, wenn
    sich ein Fremder angemeldet hat.
    """
    tenant = await _tenant(session, tenant_id)
    if tenant.status is not TenantStatus.active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "tenant is not active; provision or unsuspend it first"
        )
    row, token = await svc.create_enrollment(
        session, tenant, agent_name=payload.agent_name, issued_by="console"
    )
    await session.commit()
    await session.refresh(row)
    host = settings.connector_hostname.strip()
    return EnrollmentOut(
        id=row.id,
        agent_name=row.agent_name,
        expires_at=row.expires_at,
        token=token,
        endpoint=f"https://{host}:46200" if host else "",
    )


async def _connector_settings(session: AsyncSession, tenant_id: UUID) -> TenantConnectorSettings:
    row = await session.get(TenantConnectorSettings, tenant_id)
    if row is None:
        row = TenantConnectorSettings(tenant_id=tenant_id, allowed_ous=[], protected_groups=[])
    return row


@console.get("/connector-settings", response_model=ConnectorSettingsOut)
async def get_connector_settings(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> ConnectorSettingsOut:
    await _tenant(session, tenant_id)
    row = await session.get(TenantConnectorSettings, tenant_id)
    if row is None:
        return ConnectorSettingsOut(
            allowed_ous=[], protected_groups=[], updated_at=None, updated_by=None
        )
    return ConnectorSettingsOut(
        allowed_ous=list(row.allowed_ous),
        protected_groups=list(row.protected_groups),
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@console.put("/connector-settings", response_model=ConnectorSettingsOut)
async def put_connector_settings(
    tenant_id: UUID,
    payload: ConnectorSettingsIn,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> ConnectorSettingsOut:
    """OU-Freigabe und geschützte Gruppen setzen. Der Agent holt sie beim nächsten Abruf.

    Die Freigabe ist die Schranke zwischen Plattform und AD: der Agent läuft
    auf dem DC. Was nie freigegeben werden darf (ganze Domäne, Domain
    Controllers, Builtin, System …), lehnt diese Prüfung ab — und der Agent
    noch einmal selbst.
    """
    tenant = await _tenant(session, tenant_id)
    try:
        ous, groups = check_scope(payload.allowed_ous, payload.protected_groups)
    except ScopeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    row = await session.get(TenantConnectorSettings, tenant_id)
    if row is None:
        row = TenantConnectorSettings(tenant_id=tenant.id)
        session.add(row)
    row.allowed_ous = ous
    row.protected_groups = groups
    row.updated_at = datetime.now(UTC)
    row.updated_by = caller.actor
    await session.commit()
    await session.refresh(row)
    logger.info(
        "Connector-Freigabe für %s geändert von %s: %d OU(s), %d zusätzliche Gruppe(n)",
        tenant.slug,
        caller.actor,
        len(ous),
        len(groups),
    )
    return ConnectorSettingsOut(
        allowed_ous=list(row.allowed_ous),
        protected_groups=list(row.protected_groups),
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@console.get("/agents", response_model=list[AgentOut])
async def list_agents(
    tenant_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ConnectorAgent]:
    await _tenant(session, tenant_id)
    stmt = (
        select(ConnectorAgent)
        .where(ConnectorAgent.tenant_id == tenant_id)
        .order_by(ConnectorAgent.created_at)
    )
    return list((await session.execute(stmt)).scalars())


@console.post("/agents/{agent_id}/revoke", response_model=AgentOut)
async def revoke_agent(
    tenant_id: UUID,
    agent_id: UUID,
    payload: AgentRevoke,
    session: AsyncSession = Depends(get_session),
) -> ConnectorAgent:
    """Agent widerrufen. Wirkt bei der nächsten Anfrage.

    Es gibt keine CRL und kein OCSP: der Widerruf ist dieses Flag, und es wird
    bei **jeder** Anfrage geprüft. Eine CRL, die einmal am Tag aktualisiert
    wird, wäre langsamer und fehleranfälliger als eine Zeile in der Registry.
    """
    await _tenant(session, tenant_id)
    agent = await session.get(ConnectorAgent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown agent")
    agent.status = AgentStatus.revoked
    agent.revoked_at = datetime.now(UTC)
    agent.revoked_reason = payload.reason
    await session.commit()
    await session.refresh(agent)
    logger.info("Agent %s widerrufen", agent.id)
    return agent


@console.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    tenant_id: UUID, limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[ConnectorJob]:
    await _tenant(session, tenant_id)
    stmt = (
        select(ConnectorJob)
        .where(ConnectorJob.tenant_id == tenant_id)
        .order_by(ConnectorJob.created_at.desc())
        .limit(min(limit, 200))
    )
    return list((await session.execute(stmt)).scalars())


@console.get("/jobs/{job_id}", response_model=JobDetailOut)
async def get_job(
    tenant_id: UUID, job_id: UUID, session: AsyncSession = Depends(get_session)
) -> ConnectorJob:
    """Einen Auftrag samt Ergebnis lesen — der Weg der Datenebene.

    Sie stellt einen Auftrag ein und fragt hier, bis er fertig ist. Der
    Kundenbezug wird geprüft: eine Auftrags-Id allein genügt nicht, sie muss
    zu dem Kunden im Pfad gehören. Sonst könnte ein Kunde mit einem geratenen
    UUID das Ergebnis eines anderen lesen.
    """
    await _tenant(session, tenant_id)
    job = await session.get(ConnectorJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")
    # Verfallene Aufträge sollen als verfallen gelesen werden und nicht ewig
    # als "queued" — sonst wartet die Datenebene auf etwas, das nie kommt.
    if job.state in (JobState.queued, JobState.claimed) and job.expires_at <= datetime.now(UTC):
        await expire_stale_jobs(session, tenant_id)
        await session.commit()
        await session.refresh(job)
    return job


@console.post("/jobs", response_model=JobOut, status_code=201)
async def enqueue_job(
    tenant_id: UUID, payload: JobEnqueue, session: AsyncSession = Depends(get_session)
) -> ConnectorJob:
    """Auftrag einstellen. Die Methode muss in der Allowlist stehen.

    Auch ein Global Admin kann hier kein freies LDAP, kein PowerShell und kein
    Skript schicken — die Menge der Methoden ist geschlossen.
    """
    tenant = await _tenant(session, tenant_id)
    try:
        job = await enqueue(session, tenant, method=payload.method, payload=payload.payload)
    except MethodNotAllowedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    await session.refresh(job)
    return job


# --- Authentisierung des Agenten ------------------------------------------


async def current_agent(
    request: Request,
    x_connector_api_key: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> tuple[ConnectorAgent, Tenant]:
    """Agent aus Client-Zertifikat und API-Key bestimmen.

    Das Zertifikat kommt als **base64-kodiertes DER** im Header, den der
    Reverse Proxy setzt — nachdem **er** die Kette gegen die Plattform-CA
    verifiziert hat. Die Anwendung prüft nicht die Kette (das kann sie hier
    nicht), sondern den Fingerprint: das ist die Bindung an genau diesen
    Agenten. Beide Schichten zusammen tragen, keine allein.

    Nicht PEM, obwohl das naheliegender wäre: ein PEM enthält Zeilenumbrüche,
    und Gos ``net/http`` weist einen Header-Wert mit Zeilenumbruch ab. Caddy
    hätte damit jede Agent-Anfrage mit 502 beantwortet — gemessen, nicht
    vermutet.
    """
    encoded = request.headers.get(settings.connector_client_cert_header)
    if not encoded or not x_connector_api_key:
        logger.warning("Connector-Anfrage ohne Zertifikat oder API-Key abgewiesen")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    try:
        fingerprint = spki_fingerprint_from_der_base64(encoded)
    except CertificateIssueError:
        logger.warning("Connector-Anfrage mit unlesbarem Client-Zertifikat abgewiesen")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized") from None
    try:
        return await svc.authenticate_agent(
            session, spki_sha256=fingerprint, api_key=x_connector_api_key
        )
    except svc.ConnectorAuthError:
        # Immer dieselbe Antwort: der Anrufer erfährt nicht, welcher der vier
        # Gründe zutraf.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized") from None


@agent_api.post("/enroll", response_model=AgentEnrollResponse, status_code=201)
async def enroll(
    payload: AgentEnrollRequest, session: AsyncSession = Depends(get_session)
) -> AgentEnrollResponse:
    """Einmal-Token gegen Zertifikat und API-Key tauschen.

    Kein Client-Zertifikat nötig — der Agent hat ja noch keines. Das ist der
    einzige Endpunkt des Kanals, der ohne auskommt, und deshalb hängt alles an
    der Einmal-Einlösung des Tokens.
    """
    try:
        enrollment = await svc.redeem_enrollment(session, payload.token)
    except svc.EnrollmentError as exc:
        # 401 und nicht 400: ein abgelaufenes und ein erfundenes Token sind für
        # den Anrufer dasselbe.
        logger.warning("Anmeldung abgewiesen: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized") from None

    tenant = await session.get(Tenant, enrollment.tenant_id)
    if tenant is None or tenant.status is not TenantStatus.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")

    try:
        ca = ConnectorCa.from_settings(settings.connector_ca_cert, settings.connector_ca_key)
        issued = ca.issue(
            payload.csr_pem, tenant_slug=tenant.slug, agent_name=enrollment.agent_name
        )
    except CertificateIssueError as exc:
        # Hier ausdrücklich mit Grund: ein zu kurzer Schlüssel oder ein
        # kaputter CSR ist ein Fehler des Agenten, den die Kunden-IT beheben
        # muss. Das Token bleibt dabei uneingelöst.
        logger.warning("Zertifikatsausstellung abgelehnt: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    secrets_ = svc.AgentSecrets(api_key=svc.new_secret(), result_hmac_key=svc.new_secret())
    agent = ConnectorAgent(
        tenant_id=tenant.id,
        name=enrollment.agent_name,
        status=AgentStatus.enrolled,
        spki_sha256=issued.spki_sha256,
        certificate_serial=issued.serial_hex,
        certificate_not_after=issued.not_after,
        api_key_hash=svc.hash_api_key(secrets_.api_key),
        result_hmac_key=secrets_.result_hmac_key,
        agent_version=payload.agent_version,
    )
    session.add(agent)
    await session.flush()
    enrollment.redeemed_at = datetime.now(UTC)
    enrollment.redeemed_agent_id = agent.id
    await session.commit()
    await session.refresh(agent)
    logger.info(
        "Agent %s für Kunde %s angemeldet, SPKI %s", agent.name, tenant.slug, issued.spki_sha256
    )
    return AgentEnrollResponse(
        agent_id=agent.id,
        certificate_pem=issued.certificate_pem,
        spki_sha256=issued.spki_sha256,
        certificate_not_after=issued.not_after,
        api_key=secrets_.api_key,
        result_hmac_key=secrets_.result_hmac_key,
    )


@agent_api.post("/renew", response_model=AgentRenewResponse)
async def renew(
    payload: AgentRenewRequest,
    identity: tuple[ConnectorAgent, Tenant] = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> AgentRenewResponse:
    """Zertifikat erneuern, ohne dass ein Mensch beim Kunden vorbeimuss.

    Das Agentenzertifikat gilt 90 Tage. Ohne diesen Endpunkt wäre die
    Erneuerung ein Widerruf in der Konsole plus ein neues Einmal-Token plus
    ein Besuch beim Kunden — alle drei Monate, je Agent. Das würde niemand
    durchhalten, und die Folge wäre nicht ein sauberer Ablauf, sondern
    stillgelegte Agenten und ein längeres Zertifikat.

    Beglaubigt wird die Anfrage durch ``current_agent``: bestehendes
    Client-Zertifikat plus API-Key. Wer den aktuellen Schlüssel hat, darf
    einen neuen bekommen — und ein widerrufener Agent kommt hier nicht durch,
    weil ``authenticate_agent`` den Widerruf bei **jeder** Anfrage prüft. Das
    ist der Grund, warum der Widerruf ein Datenbank-Flag ist und keine CRL:
    eine CRL wäre morgen aktuell, und der Erneuerungs-Endpunkt wäre bis dahin
    der Weg, aus einem widerrufenen Agenten einen gültigen zu machen.

    Der Kunde wird nicht neu gewählt: er kommt aus der Agent-Zeile. Ein Agent
    kann sich also nicht in einen anderen Kunden hinein erneuern.
    """
    agent, tenant = identity
    try:
        ca = ConnectorCa.from_settings(settings.connector_ca_cert, settings.connector_ca_key)
        issued = ca.issue(payload.csr_pem, tenant_slug=tenant.slug, agent_name=agent.name)
    except CertificateIssueError as exc:
        logger.warning("Erneuerung für Agent %s abgelehnt: %s", agent.id, exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if issued.spki_sha256 == agent.spki_sha256:
        # Derselbe Schlüssel wie bisher. Zulässig wäre es, aber es hebt den
        # Zweck auf: ein Schlüssel, der über Jahre auf einem Kundenserver
        # liegt, wird nie gewechselt, und die Erneuerung ist die Gelegenheit.
        # Ausserdem wäre die Buchhaltung unten falsch — previous und current
        # wären derselbe Wert.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Der CSR trägt denselben öffentlichen Schlüssel wie das bestehende "
            "Zertifikat. Für eine Erneuerung ein neues Schlüsselpaar erzeugen.",
        )

    now = datetime.now(UTC)
    agent.previous_spki_sha256 = agent.spki_sha256
    agent.spki_rotated_at = now
    agent.spki_sha256 = issued.spki_sha256
    agent.certificate_serial = issued.serial_hex
    agent.certificate_not_after = issued.not_after
    if payload.agent_version:
        agent.agent_version = payload.agent_version
    await session.commit()
    logger.info(
        "Agent %s (%s) erneuert. Neuer SPKI %s, alter gilt noch bis %s.",
        agent.name,
        tenant.slug,
        issued.spki_sha256,
        (now + svc.ROTATION_GRACE).isoformat(),
    )
    return AgentRenewResponse(
        certificate_pem=issued.certificate_pem,
        spki_sha256=issued.spki_sha256,
        certificate_not_after=issued.not_after,
        previous_valid_until=now + svc.ROTATION_GRACE,
    )


def _opt_str(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


@agent_api.get("/config", response_model=AgentRemoteConfig)
async def agent_config(
    identity: tuple[ConnectorAgent, Tenant] = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> AgentRemoteConfig:
    """Die Konfiguration des Agenten, aus dem Cockpit (ADR-0014 Nachtrag).

    Beglaubigt wie jeder Agentenaufruf (Zertifikat + API-Key), und nur die
    eigene: der Kunde kommt aus der Agent-Zeile. Kein Geheimnis darin — der
    Agent meldet sich am AD als Maschinenkonto des DC per Kerberos an.
    """
    _agent, tenant = identity
    scope = await _connector_settings(session, tenant.id)
    desired = (await SettingsService(session).desired_state(tenant))["settings"]
    dcs_raw: object = desired.get("ad_dcs")
    ad = AgentAdSettings(
        dcs=[str(d) for d in cast(list[object], dcs_raw)] if isinstance(dcs_raw, list) else [],
        users_search_base=_opt_str(desired.get("ad_users_search_base")),
        computers_search_base=_opt_str(desired.get("ad_computers_search_base")),
        tls_verify=bool(desired.get("ad_tls_verify", True)),
        tls_ca_pem=_opt_str(desired.get("ad_tls_ca_pem")),
    )
    allowed_ous = [str(o) for o in scope.allowed_ous]
    protected_groups = [str(g) for g in scope.protected_groups]
    body = {
        "allowed_ous": allowed_ous,
        "protected_groups": protected_groups,
        "ad": ad.model_dump(),
        "poll_seconds": settings.connector_poll_seconds,
    }
    revision = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    await session.commit()
    return AgentRemoteConfig(
        allowed_ous=allowed_ous,
        protected_groups=protected_groups,
        ad=ad,
        poll_seconds=settings.connector_poll_seconds,
        revision=revision,
    )


@agent_api.post("/decommission", status_code=status.HTTP_204_NO_CONTENT)
async def decommission(
    identity: tuple[ConnectorAgent, Tenant] = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Der Agent meldet sich selbst ab — beim Deinstallieren.

    Vorher blieb nach einer Deinstallation eine gültige Anmeldung zurück, zu
    der es keinen Agenten mehr gab, bis jemand in der Konsole widerrief. Jetzt
    widerruft ``magister-connector uninstall`` sich selbst, bevor es den
    Schlüssel löscht.

    Beglaubigt wie die Erneuerung (Zertifikat plus API-Key). Ein Agent kann
    damit nur sich selbst widerrufen, nie einen anderen — und nichts, was er
    hier tut, macht einen widerrufenen Agenten wieder gültig.
    """
    agent, tenant = identity
    agent.status = AgentStatus.revoked
    agent.revoked_at = datetime.now(UTC)
    agent.revoked_reason = "Vom Agenten selbst abgemeldet (Deinstallation)"
    await session.commit()
    logger.info("Agent %s (%s) hat sich selbst abgemeldet", agent.id, tenant.slug)


#: Takt des Long-Polls. Eine halbe Sekunde: ein Passwort-Reset braucht drei
#: Aufträge nacheinander (DN suchen, Probe, Schreiben), und jeder wartet im
#: Mittel einen halben Takt.
POLL_STEP_S = 0.5


@agent_api.get("/jobs", response_model=list[JobForAgent])
async def poll_jobs(
    identity: tuple[ConnectorAgent, Tenant] = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
    wait: bool = True,
    bulk: bool = True,
) -> list[JobForAgent]:
    """Long-Poll: offene Aufträge des eigenen Kunden abholen.

    Der Kunde ergibt sich aus der Agent-Zeile, nicht aus der Anfrage — ein
    Agent kann nicht nach Aufträgen eines anderen Kunden fragen.

    Die Schleife wartet in kurzen Schritten statt in einem langen: so wirkt ein
    Widerruf oder eine Sperre spätestens beim nächsten Poll und nicht erst nach
    der vollen Wartezeit — und ein neuer Auftrag geht nach höchstens einer
    halben Sekunde hinaus.

    ``bulk=false`` schickt der Agent, solange er einen Abgleich abarbeitet: er
    will dann nur interaktive Aufträge, damit ein Passwort-Reset nicht hinter
    dem Abgleich wartet.
    """
    agent, _tenant_row = identity
    deadline = settings.connector_poll_seconds if wait else 0
    waited = 0.0
    while True:
        jobs = await claim_next(session, agent, include_bulk=bulk)
        await session.commit()
        if jobs or waited >= deadline:
            return [
                JobForAgent(id=j.id, method=j.method, payload=j.payload, expires_at=j.expires_at)
                for j in jobs
            ]
        await asyncio.sleep(POLL_STEP_S)
        waited += POLL_STEP_S


@agent_api.post("/jobs/{job_id}/result", response_model=JobOut)
async def report_result(
    job_id: UUID,
    payload: JobResultIn,
    identity: tuple[ConnectorAgent, Tenant] = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> ConnectorJob:
    """Ergebnis abliefern, mit HMAC über Auftrags-Id und Körper.

    Die HMAC beweist nicht die Identität — das tun Zertifikat und API-Key. Sie
    beweist die **Unversehrtheit** des Ergebnisses: ein Zwischenglied, das
    TLS terminiert, kann ein „ja, Passwort gesetzt" nicht in ein „nein"
    verwandeln, ohne dass es auffällt.

    Die Auftrags-Id gehört in die Signatur, sonst liesse sich ein gültig
    signiertes Ergebnis von einem Auftrag auf einen anderen umhängen.
    """
    agent, _tenant_row = identity
    body = svc.canonical_result_body(ok=payload.ok, result=payload.result, error=payload.error)
    if not svc.verify_result_signature(agent.result_hmac_key, str(job_id), body, payload.signature):
        logger.warning("Ergebnis für Auftrag %s mit falscher HMAC abgewiesen", job_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "signature mismatch")
    try:
        job = await submit_result(
            session,
            agent,
            job_id,
            ok=payload.ok,
            result=payload.result,
            error=payload.error,
        )
    except JobNotClaimableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    await session.refresh(job)
    return job
