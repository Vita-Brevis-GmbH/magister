"""Bereitstellung eines Kunden als wiederaufnehmbarer Auftrag (ADR-0013 D2).

Fünf Schritte, jeder für sich wiederholbar, in fester Reihenfolge:

1. ``create_role``   — eigene Anmelderolle ``r_<slug>`` mit eigenem Passwort
2. ``create_schema`` — ``t_<slug>``, ``REVOKE`` von PUBLIC, ``GRANT`` an die Rolle
3. ``migrate``       — Alembic auf Kopf-Version, **als die Mandantenrolle**
4. ``data_key``      — eigener Datenschlüssel für das Kunden-Audit (ADR-0013 D9)
5. ``activate``      — Status auf ``active``

Zwei Eigenschaften, die nicht verhandelbar sind:

**Nie halb angelegt.** Bricht ein Schritt ab, bleibt der Kunde auf
``provisioning``. Die Datenebene bedient nur ``active``, also ist ein halb
bereitgestellter Kunde nicht erreichbar — er antwortet mit 503, nicht mit
Teildaten.

**Jeder Schritt idempotent.** Ein Wiederaufnehmen darf nicht daran scheitern,
dass die Rolle schon existiert. Der Auftrag merkt sich zwar, wie weit er kam,
aber er verlässt sich nicht darauf: die Schritte prüfen selbst nach.

Zum Passwort: es wird hier erzeugt, auf der Rolle gesetzt und **einmal** an den
Aufrufer zurückgegeben. Es wird nicht gespeichert — nicht in der
Konsolen-Datenbank, nicht im Auftragsprotokoll, nicht im Log. Wer es verliert,
dreht es mit ``rotate_role_password`` neu. Das ist unbequemer als eine
Ablage in der Konsole und genau deshalb richtig: die Konsole kann Sitzungen in
jeden Kunden ausstellen und ist damit das höchstwertige Ziel im System; ein
Geheimnis, das dort nicht liegt, kann dort nicht gestohlen werden.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from cockpit_api.config import settings
from cockpit_api.models import (
    STEP_ORDER,
    JobStatus,
    ProvisioningJob,
    ProvisioningStep,
    Tenant,
    TenantStatus,
)

logger = logging.getLogger(__name__)

#: Bezeichner gehen unquotiert in ``CREATE ROLE`` / ``CREATE SCHEMA`` — die
#: Anweisungen nehmen keine Bind-Parameter. Diese Prüfung ist die Grenze.
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

#: Passwortlänge der Mandantenrolle. 32 Bytes URL-safe base64 ≈ 43 Zeichen.
ROLE_PASSWORD_BYTES = 32

#: Länge des Kundenschlüssels in Byte. 32 Byte Zufall, urlsafe kodiert —
#: deutlich über der Mindestlänge, die die Datenebene verlangt.
DATA_KEY_BYTES = 32

#: Erlaubte Zeichen im erzeugten Passwort. ``token_urlsafe`` liefert genau
#: diese; die Prüfung ist trotzdem da, weil das Passwort als Literal in ein
#: ``CREATE ROLE`` geht (siehe ``scram_verifier``).
PASSWORD_ALPHABET = re.compile(r"^[A-Za-z0-9_-]+$")

#: Iterationen für den SCRAM-Verifier. Postgres benutzt selbst 4096.
SCRAM_ITERATIONS = 4096

#: Zeichen, die im Verifier vorkommen dürfen: base64 plus die Trennzeichen des
#: Postgres-Formats. Kein Anführungszeichen, kein Backslash — deshalb ist er
#: als einfach gequotetes Literal sicher. Die Prüfung ist der Beleg dafür,
#: nicht eine Vermutung über die eigene Ableitungsfunktion.
VERIFIER_ALPHABET = re.compile(
    r"^SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$"
)


class ProvisioningError(RuntimeError):
    """Ein Schritt ist gescheitert. Der Kunde bleibt auf ``provisioning``."""


@dataclass(frozen=True, slots=True)
class StepOutcome:
    step: ProvisioningStep
    detail: str
    #: Nur für ``create_role``: das erzeugte Passwort, genau einmal.
    #: Wird nie in den Auftrag geschrieben.
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class JobSecrets:
    """Was ein Bereitstellungslauf herausgibt — jedes genau einmal.

    Nichts davon wird gespeichert: nicht in der Konsolen-Datenbank, nicht im
    Auftragsprotokoll, nicht im Log. Beim Kundenschlüssel kommt ein zweiter
    Grund dazu: läge er in der Konsole, wäre er in deren Sicherung — und die
    zweite Verschlüsselungsschicht über den Kunden-Dumps damit wertlos
    (ADR-0016 D2).
    """

    role_password: str | None = None
    data_key: str | None = None

    def with_secret(self, step: ProvisioningStep, value: str) -> JobSecrets:
        if step is ProvisioningStep.data_key:
            return replace(self, data_key=value)
        return replace(self, role_password=value)


def _ident(value: str, *, field: str) -> str:
    if not IDENTIFIER_PATTERN.match(value):
        raise ProvisioningError(
            f"{field}={value!r} ist kein zulässiger Bezeichner und geht nicht in SQL."
        )
    return f'"{value}"'


def new_role_password() -> str:
    return secrets.token_urlsafe(ROLE_PASSWORD_BYTES)


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    r"""SCRAM-SHA-256-Verifier für ``CREATE ROLE ... PASSWORD``.

    Warum nicht einfach das Passwort: ``CREATE ROLE`` und ``ALTER ROLE`` sind
    Utility-Statements und nehmen **keine** Bind-Parameter — das Passwort müsste
    als Literal ins SQL. Damit stünde es im Postgres-Log, sobald der Server
    ``log_statement = ddl`` (oder ``all``) führt, und in ``pg_stat_activity``,
    solange die Anweisung läuft.

    Ein vorberechneter Verifier löst das: was über die Leitung geht und
    eventuell im Log landet, ist der Verifier — daraus lässt sich das Passwort
    nicht zurückrechnen. Genau das macht ``psql \password`` auch.

    Format (Postgres, RFC 5802):
    ``SCRAM-SHA-256$<iter>:<b64 salt>$<b64 StoredKey>:<b64 ServerKey>``

    SASLprep wird übersprungen, weil ``new_role_password`` nur ASCII-Zeichen
    aus ``PASSWORD_ALPHABET`` erzeugt — dort ist SASLprep die Identität. Für
    ein fremdes Passwort gilt das nicht, deshalb die Prüfung.
    """
    if not PASSWORD_ALPHABET.match(password):
        raise ProvisioningError(
            "Das Rollenpasswort enthält Zeichen ausserhalb des erwarteten "
            "Alphabets. Der SCRAM-Verifier setzt SASLprep-neutrale ASCII-Zeichen "
            "voraus; erzeugt wird das Passwort mit new_role_password()."
        )
    if salt is None:
        salt = secrets.token_bytes(16)
    raw = password.encode("ascii")
    salted = hashlib.pbkdf2_hmac("sha256", raw, salt, SCRAM_ITERATIONS, dklen=32)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = base64.b64encode
    verifier = (
        f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{b64(salt).decode()}"
        f"${b64(stored_key).decode()}:{b64(server_key).decode()}"
    )
    if not VERIFIER_ALPHABET.match(verifier):
        raise ProvisioningError("Erzeugter SCRAM-Verifier hat ein unerwartetes Format.")
    return verifier


class TenantProvisioner:
    """Führt die Schritte gegen den Magister-Cluster aus.

    ``admin_engine`` verbindet als eine Rolle, die ``CREATEROLE`` und
    ``CREATE`` auf der Datenbank darf — nicht als Mandantenrolle. Die
    Migration läuft dagegen ausdrücklich **als** Mandantenrolle, sonst gehören
    die Tabellen dem Administrator und der Kunde bekommt beim ersten Query
    ``permission denied for table``.
    """

    def __init__(self, admin_engine: AsyncEngine, *, extension_schema: str = "public") -> None:
        self._engine = admin_engine
        self._extension_schema = extension_schema

    # -- Schritt 1 --------------------------------------------------------
    async def create_role(self, tenant: Tenant) -> StepOutcome:
        role = _ident(tenant.db_role, field="db_role")
        password = new_role_password()
        verifier = scram_verifier(password)
        async with self._engine.begin() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": tenant.db_role}
                )
            ).scalar()
            # Idempotent, aber nicht stillschweigend: eine vorhandene Rolle
            # bekommt ein neues Passwort, damit der Wiederaufnehmer eines
            # abgebrochenen Auftrags eines hat, das er kennt.
            verb = "ALTER" if exists else "CREATE"
            # exec_driver_sql, nicht text(): der Verifier enthält ':' und
            # text() würde ':4096' als Bind-Parameter lesen. Und Literal statt
            # Bind-Parameter, weil CREATE/ALTER ROLE keine annehmen — daher der
            # Verifier anstelle des Passworts.
            await conn.exec_driver_sql(f"{verb} ROLE {role} LOGIN PASSWORD '{verifier}'")
        return StepOutcome(
            ProvisioningStep.create_role,
            f"Rolle {tenant.db_role} {'aktualisiert' if exists else 'angelegt'}",
            secret=password,
        )

    # -- Schritt 2 --------------------------------------------------------
    async def create_schema(self, tenant: Tenant) -> StepOutcome:
        schema = _ident(tenant.schema_name, field="schema_name")
        role = _ident(tenant.db_role, field="db_role")
        async with self._engine.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {role}"))
            # Ohne dieses REVOKE darf in Postgres jede Rolle über PUBLIC
            # hineinsehen — der Schritt, der die Trennung überhaupt herstellt.
            await conn.execute(text(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC"))
            await conn.execute(text(f"GRANT USAGE, CREATE ON SCHEMA {schema} TO {role}"))
            # Gegenprobe an der Datenbank statt Vertrauen in die eigenen
            # Anweisungen: hat PUBLIC wirklich kein USAGE mehr?
            leaked = (
                await conn.execute(
                    text("SELECT has_schema_privilege('public', :s, 'USAGE')"),
                    {"s": tenant.schema_name},
                )
            ).scalar()
        if leaked:
            raise ProvisioningError(
                f"Schema {tenant.schema_name} ist nach dem REVOKE weiterhin für PUBLIC "
                "lesbar. Bereitstellung abgebrochen — ohne diese Grenze ist die "
                "Mandantentrennung nicht gegeben."
            )
        return StepOutcome(
            ProvisioningStep.create_schema,
            f"Schema {tenant.schema_name} angelegt, PUBLIC entzogen",
        )

    # -- Schritt 3 --------------------------------------------------------
    async def migrate(self, tenant: Tenant, *, role_password: str) -> StepOutcome:
        """Alembic auf Kopf-Version, als Mandantenrolle."""
        migrate_dir = settings.magister_api_dir
        if not migrate_dir or not Path(migrate_dir).is_dir():
            raise ProvisioningError(
                "COCKPIT_MAGISTER_API_DIR zeigt nicht auf ein Verzeichnis. Die "
                "Bereitstellung braucht das Alembic-Verzeichnis der Datenebene."
            )
        dsn = _tenant_dsn(settings.tenant_admin_dsn, tenant.db_role, role_password)
        env = dict(os.environ)
        env["MAGISTER_DATABASE_URL"] = dsn
        env["MAGISTER_MIGRATE_SCHEMA"] = tenant.schema_name
        env["MAGISTER_EXTENSION_SCHEMA"] = self._extension_schema
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            cwd=migrate_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        raw_out, raw_err = await proc.communicate()
        if proc.returncode != 0:
            tail = (raw_err or raw_out or b"").decode("utf-8", "replace").strip().splitlines()
            # Der DSN steht in der Umgebung, nicht in argv — trotzdem nur die
            # letzte Zeile übernehmen, damit kein Verbindungsstring durchsickert.
            raise ProvisioningError(
                f"Alembic ist gescheitert: {tail[-1] if tail else 'ohne Meldung'}"
            )
        stderr = (raw_err or b"").decode("utf-8", "replace")
        applied = sum(1 for line in stderr.splitlines() if "Running upgrade " in line)
        return StepOutcome(
            ProvisioningStep.migrate,
            f"{applied} Migration(en) angewendet" if applied else "schon auf dem Kopfstand",
        )

    # -- Zusatz: Passwort drehen -----------------------------------------
    async def rotate_role_password(self, tenant: Tenant) -> str:
        """Neues Passwort für die Mandantenrolle. Rückgabe genau einmal."""
        role = _ident(tenant.db_role, field="db_role")
        password = new_role_password()
        verifier = scram_verifier(password)
        async with self._engine.begin() as conn:
            await conn.exec_driver_sql(f"ALTER ROLE {role} PASSWORD '{verifier}'")
        logger.info("Passwort der Mandantenrolle für %s gedreht", tenant.slug)
        return password


def _tenant_dsn(admin_dsn: str, role: str, password: str) -> str:
    """Admin-DSN auf die Mandantenrolle umschreiben.

    ``render_as_string(hide_password=False)`` und **nicht** ``str(url)``:
    SQLAlchemy ersetzt das Passwort in ``__repr__``/``__str__`` durch ``***``,
    damit es nicht versehentlich in ein Protokoll gerät. Das ist richtig — nur
    ist dieser DSN dafür da, sich damit anzumelden. Mit ``str()`` bekäme
    Alembic das Passwort ``***`` und die Migration scheiterte an einem Cluster
    mit Passwort-Authentisierung, also an jedem produktiven.

    Der Rückgabewert ist ein Geheimnis: er geht in die Umgebung eines
    Kindprozesses und **nie** in ein Protokoll.
    """
    from sqlalchemy.engine import make_url

    return (
        make_url(admin_dsn)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )


def admin_engine() -> AsyncEngine:
    """Engine für die Verwaltungsverbindung in den Magister-Cluster.

    Bewusst ``NullPool``-artig klein und pro Auftrag aufgebaut: die Konsole
    stellt selten bereit, soll aber keine dauerhaft offene Verbindung mit
    ``CREATEROLE``-Rechten halten.
    """
    if not settings.tenant_admin_dsn:
        raise ProvisioningError(
            "COCKPIT_TENANT_ADMIN_DSN ist nicht gesetzt. Ohne Verwaltungszugang "
            "zum Magister-Cluster kann die Konsole keinen Kunden bereitstellen."
        )
    return create_async_engine(
        settings.tenant_admin_dsn, pool_size=1, max_overflow=0, pool_pre_ping=True
    )


async def run_job(
    session: AsyncSession,
    tenant: Tenant,
    job: ProvisioningJob,
    *,
    provisioner: TenantProvisioner,
    role_password: str | None = None,
) -> tuple[ProvisioningJob, JobSecrets]:
    """Auftrag von vorn oder von der Abbruchstelle weiter ausführen.

    Rückgabe: der Auftrag und die Geheimnisse dieses Laufs, jedes genau
    einmal. Zwei Felder und nicht eines: der Lauf erzeugt ein Rollenpasswort
    **und** einen Kundenschlüssel, und mit einem Feld hätte der zweite den
    ersten überschrieben — der Betreiber hätte das Rollenpasswort verloren,
    ohne es zu merken, bis die nächste Migration es braucht.
    """
    job.status = JobStatus.running
    job.attempts += 1
    job.last_error = None
    await session.flush()

    start_index = 0
    if job.last_completed_step is not None:
        start_index = STEP_ORDER.index(job.last_completed_step) + 1

    found = JobSecrets(role_password=role_password)
    for step in STEP_ORDER[start_index:]:
        try:
            outcome = await _run_step(
                session,
                tenant,
                step,
                provisioner=provisioner,
                role_password=found.role_password,
            )
        except Exception as exc:  # jeder Fehler endet gleich: Kunde bleibt provisioning
            # Der Kunde bleibt auf provisioning: nicht erreichbar ist besser
            # als halb bedient.
            job.status = JobStatus.failed
            job.last_error = f"{step.value}: {exc}"
            job.steps = [*job.steps, _entry(step, ok=False, detail=str(exc))]
            tenant.status = TenantStatus.provisioning
            logger.warning(
                "Bereitstellung von %s in Schritt %s gescheitert: %s", tenant.slug, step.value, exc
            )
            await session.flush()
            return job, found
        if outcome.secret is not None:
            found = found.with_secret(outcome.step, outcome.secret)
        job.steps = [*job.steps, _entry(step, ok=True, detail=outcome.detail)]
        job.last_completed_step = step
        await session.flush()

    job.status = JobStatus.succeeded
    await session.flush()
    logger.info("Kunde %s bereitgestellt", tenant.slug)
    return job, found


async def _run_step(
    session: AsyncSession,
    tenant: Tenant,
    step: ProvisioningStep,
    *,
    provisioner: TenantProvisioner,
    role_password: str | None,
) -> StepOutcome:
    if step is ProvisioningStep.create_role:
        return await provisioner.create_role(tenant)
    if step is ProvisioningStep.create_schema:
        return await provisioner.create_schema(tenant)
    if step is ProvisioningStep.migrate:
        if not role_password:
            # Kann beim Wiederaufnehmen passieren: die Rolle steht, das
            # Passwort kennt niemand mehr. Drehen statt raten.
            role_password = await provisioner.rotate_role_password(tenant)
            outcome = await provisioner.migrate(tenant, role_password=role_password)
            return StepOutcome(
                outcome.step, outcome.detail + " (Passwort neu gesetzt)", secret=role_password
            )
        return await provisioner.migrate(tenant, role_password=role_password)
    if step is ProvisioningStep.data_key:
        return await _provision_data_key(session, tenant)
    if step is ProvisioningStep.activate:
        tenant.status = TenantStatus.active
        tenant.schema_version = settings.expected_schema_version or None
        return StepOutcome(step, "Kunde aktiv")
    raise ProvisioningError(f"Unbekannter Schritt {step!r}")


def new_data_key() -> str:
    """Kundenschlüssel für pgcrypto. 43 Zeichen aus 32 Byte Zufall."""
    return secrets.token_urlsafe(DATA_KEY_BYTES)


async def _provision_data_key(session: AsyncSession, tenant: Tenant) -> StepOutcome:
    """Eigener Datenschlüssel je Kunde (ADR-0013 D9, ADR-0016 D8).

    Der Schlüssel wird hier erzeugt, **einmal** zurückgegeben und nirgends
    gespeichert — genau wie das Rollenpasswort und aus demselben Grund: die
    Konsole ist das höchstwertige Ziel im System, und was dort nicht liegt,
    kann dort nicht gestohlen werden. Zusätzlich gilt hier: läge der
    Kundenschlüssel in der Konsolen-Datenbank, wäre er in deren Sicherung —
    und die zweite Verschlüsselungsschicht über den Kunden-Dumps damit wertlos
    (ADR-0016 D2).

    Was die Konsole **nicht** kann, und das ist die Grenze dieses Schritts: den
    Schlüssel auf dem Anwendungsserver hinterlegen. Er gehört in dessen
    Umgebung, und dorthin reicht die Konsole nicht. Der Schritt liefert deshalb
    den Namen der Variablen mit; eingetragen wird sie beim Ausrollen. Bis das
    geschehen ist, antwortet der Mandant mit 503 — die Middleware der
    Datenebene prüft den Schlüssel, bevor sie eine Anfrage annimmt. Ein
    stiller Rückfall auf den installationsweiten Schlüssel wäre die
    schlimmere Variante: alles liefe, und die Löschzusage wäre unwahr.
    """
    ref = tenant.slug.upper()
    key = new_data_key()
    tenant.audit_key_id = f"{tenant.slug}-v1"
    await session.flush()
    return StepOutcome(
        ProvisioningStep.data_key,
        f"Kundenschlüssel erzeugt (Id {tenant.audit_key_id}). Auf dem "
        f"Anwendungsserver als MAGISTER_TENANT_AUDIT_KEY_{ref} setzen; "
        "bis dahin antwortet der Mandant mit 503.",
        secret=key,
    )


def _entry(step: ProvisioningStep, *, ok: bool, detail: str) -> dict[str, object]:
    return {
        "step": step.value,
        "ok": ok,
        "detail": detail,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
