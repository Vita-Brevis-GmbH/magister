"""Application configuration loaded from environment variables.

All Magister settings use the ``MAGISTER_`` prefix. Secrets are wrapped in
``SecretStr`` so they never accidentally land in logs or `repr()` output.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

# Env vars that were REMOVED on purpose, with the reason to show an operator.
# ``extra="ignore"`` would swallow them silently — and a security setting that
# looks like it is still in effect but is not is worse than no setting at all.
REMOVED_ENV_VARS: dict[str, str] = {
    "MAGISTER_AD_LOGIN_ENABLED": (
        "Der direkte AD-Login wurde entfernt, nicht abgeschaltet (ADR-0015 D3): "
        "kein Endpunkt nimmt mehr das Passwort eines Verzeichnisbenutzers an. "
        "Es bleiben Entra ID (OIDC) und das lokale Notkonto mit zweitem Faktor."
    ),
    "MAGISTER_AD_LOGIN_GROUP": (
        "Gehört zum entfernten AD-Login (ADR-0015 D3) und hat keine Wirkung mehr."
    ),
}

_TRUTHY = frozenset({"1", "true", "yes", "on", "y", "t"})

#: Spielraum über Pool + Overflow für die Nebenläufigkeits-Decke je Mandant
#: (ADR-0021 D3). Klein und absichtlich nicht konfigurierbar: es ist der
#: Abstand zwischen „alle Verbindungen belegt“ (normal, Millisekunden) und
#: „dieser Kunde belegt den Prozess“ (der Fall, den die Decke abfängt).
CONCURRENCY_HEADROOM = 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAGISTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+asyncpg://magister:magister@localhost:5432/magister",
    )
    # SQLAlchemy connection-pool sizing (per process). Every container opens its
    # own pool against the shared Postgres, so a per-function container split
    # multiplies connection count — keep these low and plan Postgres
    # ``max_connections`` (and PgBouncer) for the number of containers.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    # --- Mandantenfähigkeit (ADR-0013) ------------------------------------
    # JSON-Liste von Mandanten. Leer heisst: ein Mandant aus database_url,
    # Schema 'public' — der noch nicht umgezogene Bestand. Kein Schalter,
    # der das Verhalten umstellt: es ist dieselbe Registry mit einer Zeile
    # (ADR-0013 D8). Ab Phase 2 liefert die Konsole diesen Inhalt.
    tenants: str = Field(default="")
    # Pool PRO MANDANT, nicht pro Prozess. Verbindungen = Mandanten ×
    # Prozesse × (pool_size + max_overflow), deshalb klein: die harte
    # Trennung verlangt eine eigene Anmelderolle je Mandant und damit einen
    # eigenen Pool. Bei vielen Mandanten gehört ein PgBouncer davor.
    tenant_pool_size: int = Field(default=2, ge=1)
    tenant_max_overflow: int = Field(default=3, ge=0)
    # Decke für gleichzeitige Anfragen JE MANDANT und je Prozess (ADR-0021 D3).
    # Darüber gibt es 503 mit `Retry-After` statt einer Warteschlange, die den
    # Prozess für alle anderen Kunden belegt.
    #
    # ``0`` heisst **abgeleitet**: Pool + Overflow + Spielraum. Bewusst
    # abgeleitet und nicht eine zweite Zahl — eine Decke unter der Poolgrösse
    # verschenkt Verbindungen, eine weit darüber lässt Anfragen auf eine
    # Verbindung warten, die es nicht gibt. Wer sie doch von Hand setzen will,
    # kann es; dann gilt genau dieser Wert.
    tenant_max_concurrent: int = Field(default=0, ge=0)
    # Registry von der Konsole (ADR-0013 D2/D4). Leer heisst: Registry aus
    # MAGISTER_TENANTS bzw. aus database_url. Die Konsole liefert absichtlich
    # keine DSNs, nur Verweise — der DSN je Kunde steht in
    # MAGISTER_TENANT_DSN_<REF>.
    console_registry_url: str = Field(default="")
    console_registry_token: SecretStr = Field(default=SecretStr(""))
    # Marker der Konsole (ADR-0015 D1): ohne ihn verwirft sie jede Anfrage.
    console_management_marker: SecretStr = Field(default=SecretStr(""))
    # Wie oft im Hintergrund nachgeladen wird. Ein Ausfall der Konsole ändert
    # nichts am Betrieb — der letzte gute Stand bleibt gültig.
    console_registry_interval_s: int = Field(default=300, ge=30)

    # --- Operator-Zugriff (ADR-0019) --------------------------------------
    # ÖFFENTLICHER Ed25519-Schlüssel (PEM), gegen den ein Einlöseschein der
    # Konsole geprüft wird. Kein Geheimnis — deshalb als Wert und nicht als
    # Pfad, und deshalb geht die Prüfung ohne Rückfrage bei der Konsole.
    #
    # Leer heisst: es gibt die Einlöseroute **nicht** (nicht 403, gar nicht
    # da — dieselbe Linie wie ADR-0017 D1). Eine Einzelinstallation hat keinen
    # Betreiber ausser dem Kunden selbst.
    operator_public_key: str = Field(default="")
    # Wie lange eine Operator-Sitzung gilt. Kürzer als die eines Benutzers:
    # ein Support-Fall dauert eine Stunde, ein Arbeitstag nicht.
    operator_session_minutes: int = Field(default=60, ge=5, le=480)

    # AD über den Connector-Agenten (ADR-0014). Eingeschaltet, sobald eine
    # Konsolen-URL steht und der Kunde eine console_id in der Registry hat —
    # kein eigener Schalter, sondern eine Folge der Konfiguration.
    # Reihenfolge der Rücken: ad_rpc_url gewinnt (ADR-0011, eigener
    # AD-Container im selben Netz), dann der Connector, dann direkt.
    ad_connector_enabled: bool = Field(default=False)

    # Schema, in dem die Erweiterungen liegen (pgcrypto für den Audit-Dienst).
    # Steht als ZWEITER Eintrag auf dem search_path und darf keine
    # Anwendungstabellen enthalten — sonst könnte eine im Mandantenschema
    # fehlende Tabelle still darauf zurückfallen.
    extension_schema: str = Field(default="public")

    audit_key: SecretStr = Field(
        default=SecretStr(""),
        description="Symmetric key for pgcrypto pgp_sym_encrypt of audit_events.payload.",
    )
    audit_key_id: str = Field(
        default="v1",
        description=(
            "Identifier for the currently active audit_key. Stored alongside "
            "each event so multi-key rotation (M-03 hardening) can decrypt "
            "old rows with the previous key while new writes use the current."
        ),
    )
    secrets_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Optional dedicated pgcrypto key for the app_settings secrets "
            "(oidc_client_secret, ad_bind_password). Falls back to audit_key "
            "when empty, so leaving it unset keeps current behaviour. Setting a "
            "distinct value requires re-entering those secrets once (they are "
            "then re-encrypted with the new key)."
        ),
    )

    def tenant_concurrency_limit(self) -> int:
        """Wirksame Decke je Mandant und Prozess (ADR-0021 D3).

        Der Spielraum über dem Pool ist Absicht: eine Anfrage, die gerade
        keine Verbindung hat, ist normal (sie wartet Millisekunden), und die
        Decke soll den Ausnahmefall abfangen und nicht den Alltag.
        """
        if self.tenant_max_concurrent:
            return self.tenant_max_concurrent
        return self.tenant_pool_size + self.tenant_max_overflow + CONCURRENCY_HEADROOM

    def app_secrets_key(self) -> str:
        """Key for the app_settings secret columns; falls back to audit_key."""
        return self.secrets_key.get_secret_value() or self.audit_key.get_secret_value()

    oidc_issuer: str = Field(default="")
    oidc_client_id: str = Field(default="")
    oidc_client_secret: SecretStr = Field(default=SecretStr(""))
    oidc_redirect_uri: str = Field(default="http://localhost:8000/auth/callback")
    oidc_scopes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["openid", "profile", "email"]
    )

    session_secret: SecretStr = Field(default=SecretStr(""))
    session_lifetime_minutes: int = Field(default=480)
    session_cookie_name: str = Field(default="magister_session")
    session_cookie_secure: bool = Field(default=True)

    csrf_secret: SecretStr = Field(default=SecretStr(""))
    csrf_cookie_name: str = Field(default="magister_csrf")
    csrf_header_name: str = Field(default="X-CSRF-Token")

    bootstrap_admins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # M6 Phase 3 / ADR-0008 D5 — split-fähig: which feature modules THIS
    # container mounts. Empty (default) = every module (the single-container
    # monolith). Set e.g. ``MAGISTER_CONTAINER_MODULES=departments`` to run this
    # image as a dedicated per-module container (own scaling / fault isolation)
    # behind a path-routing reverse proxy. The non-toggleable ``platform`` base
    # is ALWAYS mounted (auth/session/me), so a module container can still
    # authenticate. Unknown ids are rejected at startup. This is the deployment
    # axis; the per-request enable/disable "Schieber" stays independent.
    container_modules: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Container-role flag (split plan, Phase 0). The periodic AD sync — the
    # recurring AD *read* — must run in exactly ONE container, not in every
    # one. The single AD-owning container keeps this True (default); every other
    # container in a split deployment sets ``MAGISTER_RUN_SCHEDULER=0`` so it
    # never opens a second sync loop against AD + DB.
    run_scheduler: bool = Field(default=True)

    # Strict AD boundary (ADR-0011). When set, this process holds NO AD
    # credentials and reaches Active Directory only through the AD-owning
    # container's internal RPC at this base URL (e.g.
    # ``http://magister-api-ad:8000``); ``get_ad_client`` then returns an
    # ``AdRpcClient`` instead of a direct ``AdClient``. Unset (default) = this
    # process talks to AD directly — the single-container monolith and the AD
    # container itself. ``ad_rpc_secret`` is the shared bearer the client sends
    # and the server requires (never logged).
    ad_rpc_url: str | None = Field(default=None)
    ad_rpc_secret: SecretStr | None = Field(default=None)

    # Local-admin (break-glass) — only consulted on first boot when the
    # `local_admins` table is empty. Always pass a pre-computed argon2id
    # hash; plaintext is refused. See `magister-cli hash-password`.
    # Second factor for the local break-glass account (ADR-0015 D2). On by
    # default: the local path was the last one without one. Turning it off is a
    # deliberate, documented downgrade — not a convenience.
    local_mfa_required: bool = Field(default=True)
    local_admin_username: str = Field(default="admin")
    local_admin_password_hash: SecretStr | None = Field(default=None)

    ad_dcs: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ad_bind_mode: str = Field(
        default="simple",
        description=(
            "Service-account bind mode: 'simple' (DN + password over LDAPS) or "
            "'gssapi' (Kerberos/keytab, no stored password). See ad-gssapi-bind runbook."
        ),
    )
    ad_bind_dn: str | None = None
    ad_bind_password: SecretStr | None = None
    ad_users_search_base: str | None = Field(
        default=None,
        description=(
            "LDAP search base for the periodic user sync (e.g. OU=Users,DC=schule,DC=local)."
        ),
    )
    ad_sync_interval_minutes: int = Field(default=15)
    # Safety guardrail for the full-sync "missing user" marker: never flag more
    # than this fraction of the cache (and never more than an absolute floor)
    # in one run — a too-narrow search base would otherwise flag everyone.
    ad_sync_missing_max_ratio: float = Field(default=0.2, ge=0.0, le=1.0)
    ad_sync_missing_floor: int = Field(default=10, ge=0)
    ad_use_mock: bool = Field(
        default=False,
        description="When true the AD client uses ldap3's MOCK_SYNC strategy (tests).",
    )
    ad_ca_bundle_path: str | None = Field(
        default=None,
        description=(
            "Optional path to a PEM CA bundle that the LDAPS connection must "
            "verify the domain-controller cert against. When unset, ldap3 "
            "falls back to the OS trust store. Pin this to the Schulträger "
            "root CA for defence-in-depth against a compromised system CA."
        ),
    )
    web_cert_dir: str | None = Field(
        default=None,
        description=(
            "Directory shared with the Caddy reverse proxy where the effective "
            "webserver certificate is materialized (tls.pem/tls.key + a Caddy "
            "tls snippet). Unset = certificate materialization is skipped (dev/"
            "tests). In Compose this is the shared web_certs volume (e.g. /certs)."
        ),
    )

    ops_dir: str | None = Field(
        default=None,
        description=(
            "Directory shared with the host ops-agent for WebUI-triggered "
            "container restart / git-update. The API only WRITES request files "
            "into <ops_dir>/requests and READS <ops_dir>/status.json — it never "
            "runs Docker itself. A privileged host watcher executes the requests. "
            "Unset = the System restart/update controls are disabled (dev/tests)."
        ),
    )
    ad_tls_ca_pem: str | None = Field(
        default=None,
        description=(
            "Optional inline PEM CA bundle (managed from the admin GUI). Takes "
            "precedence over ``ad_ca_bundle_path`` when set. Public data, not a "
            "secret."
        ),
    )
    ad_tls_verify: bool = Field(
        default=True,
        description=(
            "When false, the LDAPS connection does NOT validate the "
            "domain-controller certificate (still encrypted, but unauthenticated "
            "transport — vulnerable to MITM). Intended only as a stop-gap while a "
            "proper CA is imported. Every disabled state is audited."
        ),
    )
    ad_computers_search_base: str | None = Field(
        default=None,
        description=(
            "Optional LDAP base for the Computer-OU walk. Unset = device "
            "sync is skipped; device_name in ad_user_cache stays as-is."
        ),
    )

    rate_limit_auth: str = Field(default="10/minute")
    rate_limit_password_reset: str = Field(default="10/minute")

    @field_validator(
        "bootstrap_admins", "ad_dcs", "oidc_scopes", "container_modules", mode="before"
    )
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("environment")
    @classmethod
    def _check_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got {v!r}")
        return v

    @field_validator("ad_bind_mode")
    @classmethod
    def _check_bind_mode(cls, v: str) -> str:
        if v not in {"simple", "gssapi"}:
            raise ValueError(f"ad_bind_mode must be 'simple' or 'gssapi', got {v!r}")
        return v

    def require_runtime_secrets(self) -> None:
        """Raise if a runtime-required secret is empty.

        Only the cryptographic + DB env vars are mandatory now — OIDC + AD
        config moved into the ``app_settings`` table (M1.5b) and is editable
        from the GUI. The lifespan-seed copies any pre-existing
        ``MAGISTER_OIDC_*`` / ``MAGISTER_AD_*`` env into the DB on first
        boot, so existing deployments keep working without env after the
        upgrade.

        Intentionally NOT called at import time so unit tests can run with
        partial config; the FastAPI app factory calls this on startup.
        """
        missing: list[str] = []
        if not self.audit_key.get_secret_value():
            missing.append("MAGISTER_AUDIT_KEY")
        if not self.session_secret.get_secret_value():
            missing.append("MAGISTER_SESSION_SECRET")
        if not self.csrf_secret.get_secret_value():
            missing.append("MAGISTER_CSRF_SECRET")
        if missing:
            raise RuntimeError("Missing required runtime secrets: " + ", ".join(missing))

    @staticmethod
    def reject_removed_env(environ: Mapping[str, str] | None = None) -> None:
        """Refuse to start when a removed security setting is still switched ON.

        A truthy leftover means the operator believes a login path exists that
        no longer does — that must not pass silently, so it aborts the start. A
        falsy leftover (``0``/``false``) is only stale config: it gets a loud
        log line, but blocking an upgrade over it would be friction without any
        security gain.
        """
        env = os.environ if environ is None else environ
        fatal: list[str] = []
        for name, reason in REMOVED_ENV_VARS.items():
            raw = env.get(name)
            if raw is None:
                continue
            value = raw.strip()
            if value and value.lower() in _TRUTHY:
                fatal.append(f"{name}: {reason}")
            elif value:
                logger.warning(
                    "%s ist noch gesetzt (%r), hat aber keine Wirkung mehr. %s "
                    "Bitte aus der Konfiguration entfernen.",
                    name,
                    value,
                    reason,
                )
        if fatal:
            raise RuntimeError(
                "Entfernte Einstellungen sind noch aktiviert:\n  - " + "\n  - ".join(fatal)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
