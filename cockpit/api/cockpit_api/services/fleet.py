"""Befunde über die Connector-Flotte (ADR-0021 D6).

Die Konsole **zeigt** die Flotte schon: Version, Zertifikatsablauf,
`last_seen_at`. Was fehlte, ist der Unterschied zwischen Anzeigen und
Überwachen — ein Agent, der seit drei Tagen still ist, und ein Zertifikat, das
in fünf Tagen abläuft, sehen in einer Liste aus wie alles andere.

Dieses Modul rechnet daraus **Befunde**: eine Liste von Dingen, die jemand
ansehen muss, mit Schweregrad. Es alarmiert nicht selbst. Der Alarm kommt aus
`cli/fleet_check.py` über einen Exit-Code, den die bestehende Überwachung
liest — kein SMTP in Magister, keine Webhooks, keine zweite Alarmierung neben
der, die es im Betrieb schon gibt. Dieselbe Überlegung wie bei den
Quell-IP-Regeln, die ausdrücklich nicht in Magister nachgebaut werden.

**Die Schwellen sind nicht frei gewählt**, sie folgen aus dem Verhalten des
Agenten:

* Er erneuert sein Zertifikat **30 Tage** vor Ablauf (`RENEW_BEFORE_DAYS` im
  Agenten) und prüft das täglich. Ein Zertifikat mit weniger als 28 Tagen
  Restlaufzeit heisst deshalb nicht „läuft bald ab“ — es heisst **die
  Erneuerung findet nicht statt**. Das ist der Befund, und er ist zwei Tage
  nach dem erwarteten Erneuerungsfenster fällig, nicht erst kurz vor Schluss.
* Er meldet sich im Minutentakt. Nach `STALE_AFTER` (5 Minuten) gilt er in der
  Anwendung als abgehängt — für einen **Alarm** ist das zu zappelig, weil ein
  Neustart des Kundenservers dazwischenkommt. Eine Stunde Stille ist ein
  Befund, ein Tag Stille ist einer mit Nachdruck.
* Die Agent-Version wird gegen den **höchsten Stand der eigenen Flotte**
  verglichen und nicht gegen eine konfigurierte Zahl. Entscheid E10 sagt:
  Updates laufen automatisch. Wenn einer zurückhängt, während die anderen
  weiter sind, ist sein Update stehen geblieben — und das lässt sich ohne eine
  zweite Einstellung feststellen, die mit der Wahrheit auseinanderläuft.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models import AgentStatus, ConnectorAgent, Tenant, TenantStatus

#: Der Agent erneuert 30 Tage vor Ablauf und prüft täglich. Zwei Tage
#: Spielraum, dann ist die Erneuerung überfällig und nicht bloss „bald“.
RENEWAL_DUE_DAYS = 28

#: Darunter ist es kein Hinweis mehr, sondern knapp: eine Woche.
CERT_CRITICAL_DAYS = 7

#: Stille, ab der es ein Befund ist. Deutlich über `STALE_AFTER` (5 Minuten),
#: weil ein Neustart des Kundenservers keinen Alarm auslösen soll.
SILENT_WARN = timedelta(hours=1)
SILENT_CRITICAL = timedelta(hours=24)

#: So lange darf ein ausgestelltes Paket unbenutzt liegen, bevor es auffällt.
#: Das Einmal-Token verfällt nach 24 Stunden; danach ist ein Agent, der sich
#: nie gemeldet hat, ein Onboarding, das nicht fertig geworden ist.
NEVER_SEEN_AFTER = timedelta(hours=36)


class Severity(StrEnum):
    """Zwei Stufen, und mehr braucht es nicht.

    `warning` heisst: jemand soll hinsehen. `critical` heisst: jemand soll
    heute hinsehen. Eine dritte Stufe wäre eine, die niemand von der zweiten
    unterscheidet.
    """

    warning = "warning"
    critical = "critical"


#: Exit-Codes nach der Konvention, die jedes Überwachungssystem versteht
#: (Nagios und alles, was sich daran orientiert). Bewusst keine eigene
#: Nummerierung: der Sinn eines Exit-Codes ist, dass ihn etwas anderes liest.
EXIT_OK = 0
EXIT_WARNING = 1
EXIT_CRITICAL = 2


@dataclass(frozen=True, slots=True)
class Finding:
    """Ein Befund. `detail` ist für Menschen, `kind` für Maschinen."""

    kind: str
    severity: Severity
    tenant_slug: str
    agent_name: str | None
    detail: str


def _days_left(not_after: datetime, now: datetime) -> int:
    return (not_after - now).days


def _certificate_findings(agent: ConnectorAgent, slug: str, now: datetime) -> list[Finding]:
    days = _days_left(agent.certificate_not_after, now)
    if days < 0:
        return [
            Finding(
                kind="certificate_expired",
                severity=Severity.critical,
                tenant_slug=slug,
                agent_name=agent.name,
                detail=(
                    f"Zertifikat seit {abs(days)} Tag(en) abgelaufen. Der Agent "
                    "kommt nicht mehr herein; Passwort-Resets bei diesem Kunden "
                    "scheitern. Neu anmelden (Einmal-Token)."
                ),
            )
        ]
    if days <= CERT_CRITICAL_DAYS:
        return [
            Finding(
                kind="renewal_overdue",
                severity=Severity.critical,
                tenant_slug=slug,
                agent_name=agent.name,
                detail=(
                    f"Zertifikat läuft in {days} Tag(en) ab, die automatische "
                    f"Erneuerung hätte {30 - days} Tag(e) Zeit gehabt. Sie findet "
                    "nicht statt — Log des Agenten ansehen."
                ),
            )
        ]
    if days <= RENEWAL_DUE_DAYS:
        return [
            Finding(
                kind="renewal_overdue",
                severity=Severity.warning,
                tenant_slug=slug,
                agent_name=agent.name,
                detail=(
                    f"Zertifikat läuft in {days} Tag(en) ab. Der Agent erneuert "
                    "30 Tage vorher; dass es noch steht, heisst: die Erneuerung "
                    "ist nicht gelaufen."
                ),
            )
        ]
    return []


def _contact_findings(agent: ConnectorAgent, slug: str, now: datetime) -> list[Finding]:
    if agent.last_seen_at is None:
        # Nie gemeldet. Direkt nach dem Anlegen ist das normal — das Paket ist
        # unterwegs. Nach der Frist ist es ein Onboarding, das hängen blieb.
        if now - agent.created_at > NEVER_SEEN_AFTER:
            return [
                Finding(
                    kind="agent_never_seen",
                    severity=Severity.warning,
                    tenant_slug=slug,
                    agent_name=agent.name,
                    detail=(
                        "Seit dem Anlegen kein einziger Kontakt. Einmal-Token "
                        "verfallen (24 Stunden) — das Paket wurde nie "
                        "installiert oder der Port 46200 ist zu."
                    ),
                )
            ]
        return []
    silent = now - agent.last_seen_at
    if silent > SILENT_CRITICAL:
        return [
            Finding(
                kind="agent_silent",
                severity=Severity.critical,
                tenant_slug=slug,
                agent_name=agent.name,
                detail=(
                    f"Seit {silent.days} Tag(en) still. Bei diesem Kunden ist "
                    "kein Passwort-Reset möglich."
                ),
            )
        ]
    if silent > SILENT_WARN:
        minutes = int(silent.total_seconds() // 60)
        return [
            Finding(
                kind="agent_silent",
                severity=Severity.warning,
                tenant_slug=slug,
                agent_name=agent.name,
                detail=f"Seit {minutes} Minuten still (erwartet: Kontakt im Minutentakt).",
            )
        ]
    return []


def _version_findings(agents: list[tuple[ConnectorAgent, str]]) -> list[Finding]:
    """Wer hinter dem höchsten Stand der eigenen Flotte liegt.

    Verglichen wird als Zeichenkette und nicht als Versionsnummer: die
    Agent-Versionen sind Release-Tags derselben Quelle, und ein
    Versionsvergleich mit allen Sonderfällen (`1.10` gegen `1.9`) wäre eine
    Bibliothek für eine Information, die auch so trägt — „nicht der höchste
    Stand" genügt, und das Detail nennt beide Werte.
    """
    known = [(a, slug) for a, slug in agents if a.agent_version]
    if len(known) < 2:
        # Mit einem Agenten gibt es keinen Vergleich, und eine erfundene
        # Sollversion wäre eine zweite Wahrheit.
        return []
    newest = max(a.agent_version or "" for a, _ in known)
    return [
        Finding(
            kind="agent_version_behind",
            severity=Severity.warning,
            tenant_slug=slug,
            agent_name=agent.name,
            detail=(
                f"Agent läuft auf {agent.agent_version}, die Flotte ist bei "
                f"{newest}. Updates laufen automatisch (E10) — dass dieser "
                "zurückhängt, heisst, sein Update ist stehen geblieben."
            ),
        )
        for agent, slug in known
        if (agent.agent_version or "") != newest
    ]


async def fleet_findings(session: AsyncSession, *, now: datetime | None = None) -> list[Finding]:
    """Alle Befunde, schwerste zuerst.

    Widerrufene Agenten kommen nicht vor: ein widerrufenes Zertifikat läuft ab,
    ohne dass es jemanden interessiert, und ein widerrufener Agent, der still
    ist, ist die Absicht.
    """
    moment = now or datetime.now(UTC)
    agents = list(
        (
            await session.execute(
                select(ConnectorAgent, Tenant.slug)
                .join(Tenant, Tenant.id == ConnectorAgent.tenant_id)
                .where(ConnectorAgent.status != AgentStatus.revoked)
                .where(ConnectorAgent.revoked_at.is_(None))
                .order_by(Tenant.slug, ConnectorAgent.name)
            )
        ).all()
    )
    pairs: list[tuple[ConnectorAgent, str]] = [(agent, slug) for agent, slug in agents]

    findings: list[Finding] = []
    for agent, slug in pairs:
        findings.extend(_certificate_findings(agent, slug, moment))
        findings.extend(_contact_findings(agent, slug, moment))
    findings.extend(_version_findings(pairs))

    # Ein aktiver Kunde ohne Agenten kann keine Passwörter zurücksetzen. Das
    # ist kein Agenten-Befund, sondern einer über die Lücke.
    with_agent = {slug for _, slug in pairs}
    active = list(
        (
            await session.execute(
                select(Tenant.slug)
                .where(Tenant.status == TenantStatus.active)
                .order_by(Tenant.slug)
            )
        )
        .scalars()
        .all()
    )
    findings.extend(
        Finding(
            kind="tenant_without_agent",
            severity=Severity.warning,
            tenant_slug=slug,
            agent_name=None,
            detail=(
                "Aktiver Kunde ohne angemeldeten Agenten — bei ihm ist kein Passwort-Reset möglich."
            ),
        )
        for slug in active
        if slug not in with_agent
    )

    # Schwerste zuerst, danach nach Kunde: eine Liste, die man von oben liest.
    order = {Severity.critical: 0, Severity.warning: 1}
    return sorted(findings, key=lambda f: (order[f.severity], f.tenant_slug, f.kind))


def exit_code(findings: list[Finding]) -> int:
    """Der Exit-Code für die Überwachung."""
    if any(f.severity is Severity.critical for f in findings):
        return EXIT_CRITICAL
    if findings:
        return EXIT_WARNING
    return EXIT_OK


__all__ = [
    "CERT_CRITICAL_DAYS",
    "EXIT_CRITICAL",
    "EXIT_OK",
    "EXIT_WARNING",
    "NEVER_SEEN_AFTER",
    "RENEWAL_DUE_DAYS",
    "SILENT_CRITICAL",
    "SILENT_WARN",
    "Finding",
    "Severity",
    "exit_code",
    "fleet_findings",
]
