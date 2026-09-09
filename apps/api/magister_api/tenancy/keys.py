"""Kundenschlüssel je Mandant (ADR-0016 D8).

``audit_events.payload``, ``ad_user_cache.password_enc`` und die Geheimnisse in
``app_settings`` liegen als pgcrypto-Chiffrat in der Datenbank. Der Schlüssel
dazu kam bisher aus **einer** Umgebungsvariablen (``MAGISTER_AUDIT_KEY``) —
richtig für eine Installation mit einem Kunden, falsch für eine gehostete mit
zwanzig. Zwei Zusagen aus ADR-0016 hängen daran, und beide sind mit einem
gemeinsamen Schlüssel unwahr:

* **Crypto-Shredding (D8).** „Nach dem Vernichten des Kundenschlüssels ist kein
  Audit-Payload dieses Kunden mehr entschlüsselbar." Mit einem gemeinsamen
  Schlüssel vernichtet man beim Offboarding eines Kunden die Audit-Payloads
  **aller** Kunden — oder man vernichtet nichts. Beides ist unbrauchbar.
* **Zweite Schicht im Backup (D2).** „Ein gestohlenes Backup gibt ohne den
  Kundenschlüssel keine Audit-Payloads her." Mit einem gemeinsamen Schlüssel
  öffnet der eine Schlüssel die Dumps aller Kunden.

Deshalb: ein Schlüssel je Mandant, aus der **Umgebung** und nicht aus der
Datenbank. Aus der Datenbank wäre er im Dump, und die zweite Schicht damit
wieder weg — derselbe Grund, aus dem der DSN in der Konsole nur als Verweis
steht (ADR-0013 D2).

Fehlt der Schlüssel bei mehr als einem Mandanten, wird **abgelehnt** und nicht
auf den gemeinsamen zurückgefallen. Ein Rückfall wäre die Variante, die
niemandem auffällt: alles läuft, und die beiden Zusagen oben sind still
gebrochen. Bei genau einem Mandanten ist der Rückfall dagegen richtig — dort
gibt es nichts zu trennen, und eine bestehende Installation soll nach dem
Update ohne neue Konfiguration weiterlaufen.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from magister_api.config import Settings

logger = logging.getLogger(__name__)

#: Umgebungsvariablen je Mandant. ``<REF>`` ist der Slug in Grossbuchstaben —
#: dieselbe Regel wie beim DSN-Verweis (``MAGISTER_TENANT_DSN_<REF>``), damit
#: ein Betreiber nicht zwei Namensschemata im Kopf halten muss.
ENV_AUDIT_KEY = "MAGISTER_TENANT_AUDIT_KEY_{ref}"
ENV_AUDIT_KEY_ID = "MAGISTER_TENANT_AUDIT_KEY_ID_{ref}"
ENV_SECRETS_KEY = "MAGISTER_TENANT_SECRETS_KEY_{ref}"

#: Kürzeste Länge, die wir für einen **neu konfigurierten** Schlüssel
#: annehmen. Kein Ersatz für einen ordentlich erzeugten Schlüssel, aber es
#: fängt den Tippfehler und das Platzhalterwort.
#:
#: Ausdrücklich **nicht** rückwirkend auf ``MAGISTER_AUDIT_KEY`` einer
#: bestehenden Installation: dort liegen Audit-Payloads, die mit genau diesem
#: Schlüssel verschlüsselt sind. Ihn zu wechseln ist eine Umschlüsselung aller
#: Zeilen, keine Konfigurationsänderung — eine Ablehnung wäre also nicht
#: „bitte einen längeren Schlüssel", sondern „diese Installation antwortet ab
#: dem Update mit 503". Für den Bestand steht deshalb eine Warnung, für einen
#: neuen Mandantenschlüssel eine Ablehnung.
MIN_KEY_LENGTH = 32

_REF_ALLOWED = re.compile(r"^[A-Z0-9_]+$")


class TenantKeyError(RuntimeError):
    """Der Kundenschlüssel fehlt oder ist unbrauchbar."""


@dataclass(frozen=True, slots=True)
class TenantKeys:
    """Die Schlüssel eines Mandanten. Wird nie protokolliert."""

    audit_key: str
    audit_key_id: str
    secrets_key: str

    def __repr__(self) -> str:  # pragma: no cover - Schutz gegen Zufallsfunde
        # Ohne dieses ``__repr__`` steht der Schlüssel in jedem Traceback, in
        # dem dieses Objekt in einem Frame liegt.
        return f"TenantKeys(audit_key_id={self.audit_key_id!r}, ...)"


def env_ref(slug: str) -> str:
    """Slug in die Form der Umgebungsvariablen bringen."""
    ref = slug.upper().replace("-", "_")
    if not _REF_ALLOWED.match(ref):
        raise TenantKeyError(f"slug={slug!r} ergibt keinen zulässigen Umgebungs-Verweis.")
    return ref


def resolve_tenant_keys(
    slug: str,
    *,
    fallback_audit_key: str,
    fallback_audit_key_id: str,
    fallback_secrets_key: str,
    single_tenant: bool,
    env: Mapping[str, str] | None = None,
) -> TenantKeys:
    """Schlüssel dieses Mandanten bestimmen.

    ``fallback_*`` sind die Werte aus den bisherigen, mandantenlosen
    Einstellungen. Sie gelten **nur** bei genau einem Mandanten; sonst ist ein
    fehlender Schlüssel ein Fehler.
    """
    source = os.environ if env is None else env
    ref = env_ref(slug)
    audit = (source.get(ENV_AUDIT_KEY.format(ref=ref)) or "").strip()
    key_id = (source.get(ENV_AUDIT_KEY_ID.format(ref=ref)) or "").strip()
    secrets = (source.get(ENV_SECRETS_KEY.format(ref=ref)) or "").strip()

    if audit and len(audit) < MIN_KEY_LENGTH:
        raise TenantKeyError(
            f"{ENV_AUDIT_KEY.format(ref=ref)} ist kürzer als {MIN_KEY_LENGTH} "
            "Zeichen. Der Wert ist neu konfiguriert, also kostet ein längerer "
            "nichts: openssl rand -base64 32."
        )
    if not audit:
        if not single_tenant:
            raise TenantKeyError(
                f"{ENV_AUDIT_KEY.format(ref=ref)} ist nicht gesetzt. Bei mehr als "
                "einem Mandanten braucht jeder seinen eigenen Kundenschlüssel — "
                "ein gemeinsamer würde bedeuten, dass das Offboarding eines "
                "Kunden die Audit-Inhalte aller Kunden vernichtet und ein "
                "gestohlenes Backup die Inhalte aller Kunden hergibt "
                "(ADR-0016 D2, D8)."
            )
        audit = fallback_audit_key.strip()
        key_id = key_id or fallback_audit_key_id.strip()
        secrets = secrets or fallback_secrets_key.strip()
        if not audit:
            raise TenantKeyError(
                "Weder MAGISTER_TENANT_AUDIT_KEY_"
                f"{ref} noch MAGISTER_AUDIT_KEY ist gesetzt. Ohne Kundenschlüssel "
                "kann kein Audit-Ereignis geschrieben werden."
            )
        if len(audit) < MIN_KEY_LENGTH:
            # Warnung, keine Ablehnung: siehe MIN_KEY_LENGTH. Mit diesem
            # Schlüssel sind bestehende Zeilen verschlüsselt.
            logger.warning(
                "MAGISTER_AUDIT_KEY ist kürzer als %d Zeichen. Ein Wechsel "
                "verlangt eine Umschlüsselung aller Audit-Payloads und "
                "gespeicherten Passwörter — einplanen, nicht im Betrieb ändern.",
                MIN_KEY_LENGTH,
            )
    # Ohne eigene Id wären zwei Kunden im Dump nicht unterscheidbar: die
    # Sicherung vermerkt nur die Id, und wer wiederherstellt, sucht damit den
    # passenden Schlüssel. ``v1`` bei allen hilft dabei nicht.
    return TenantKeys(
        audit_key=audit,
        audit_key_id=key_id or f"{slug}-v1",
        secrets_key=secrets or audit,
    )


#: Schlüssel, unter dem die Mandantenschlüssel an der Sitzung hängen.
#:
#: Warum an der **Sitzung** und nicht in den Einstellungen: die sechs Stellen,
#: die pgcrypto aufrufen (Audit-Dienst, Passwort-Tresor, app_settings, TOTP,
#: Privacy, Import), bekommen ihre ``Settings`` über ``Depends(get_settings)``
#: — und das ist ein prozessweit gecachtes Objekt ohne Mandantenbezug. Eine
#: Sitzung dagegen ist immer schon die eines Mandanten: ``db.get_session``
#: löst den Mandanten auf, setzt ``search_path`` und öffnet die Verbindung mit
#: dessen Anmelderolle. Der Schlüssel gehört an dieselbe Stelle wie die
#: Verbindung, auf der die Zeile geschrieben wird.
#:
#: Ein ContextVar wäre die andere Möglichkeit gewesen. Dagegen spricht, dass
#: Starlettes Middleware den Endpunkt in einer eigenen Task ausführt — ob eine
#: dort gesetzte Variable ankommt, hängt an der Starlette-Version. Diese
#: Kopplung soll nicht von einer Bibliotheksversion abhängen.
SESSION_INFO_KEY = "tenant_keys"


def attach_keys(session: AsyncSession, keys: TenantKeys) -> None:
    session.info[SESSION_INFO_KEY] = keys


def keys_for(session: AsyncSession, settings: Settings) -> TenantKeys:
    """Schlüssel dieser Sitzung, sonst die der Einstellungen.

    Der Rückfall gilt für Aufrufer ohne Anfrage: CLI-Werkzeuge, der
    AD-Abgleich-Scheduler, Tests. Die haben keinen Mandanten im Anfragepfad,
    und ihre Einstellungen sind genau die der Installation. Im Anfragepfad
    kommt es nie dazu — dort hängt ``db.get_session`` die Schlüssel an, und
    die Middleware hat vorher geprüft, dass es sie gibt.
    """
    attached = session.info.get(SESSION_INFO_KEY)
    if isinstance(attached, TenantKeys):
        return attached
    return TenantKeys(
        audit_key=settings.audit_key.get_secret_value(),
        audit_key_id=settings.audit_key_id,
        secrets_key=settings.app_secrets_key(),
    )


__all__ = [
    "ENV_AUDIT_KEY",
    "ENV_AUDIT_KEY_ID",
    "ENV_SECRETS_KEY",
    "MIN_KEY_LENGTH",
    "SESSION_INFO_KEY",
    "TenantKeyError",
    "TenantKeys",
    "attach_keys",
    "env_ref",
    "keys_for",
    "resolve_tenant_keys",
]
