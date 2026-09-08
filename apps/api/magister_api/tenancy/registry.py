"""Mandanten-Registry (ADR-0013 D1).

Eine Zeile pro Kunde, und jede Zeile trägt **DSN plus Schema**. Damit sind
„eigenes Schema", „eigene Datenbank" und „eigener Cluster" derselbe Code-Pfad
und unterscheiden sich nur im Eintrag — ein Kunde wird umgezogen, nicht umgebaut.

In Phase 1 kommt die Registry aus der Umgebung (``MAGISTER_TENANTS``); ab Phase 2
liest ein Reconciler sie aus der Konsolen-Datenbank. Die Schnittstelle hier
bleibt dieselbe, damit der Wechsel keine Aufrufstelle anfasst.

Warum die Validierung so streng ist: ``SET LOCAL ROLE`` und
``SET LOCAL search_path`` nehmen **keine** Bind-Parameter. Schema- und
Rollennamen landen also als Text im SQL. Die Prüfung beim Laden ist damit
die Sicherheitsgrenze, nicht eine Bequemlichkeit — deshalb ein strenges
Muster und ein Start, der bei Verstoss abbricht statt zu warnen.

Und der Grund für ``_require_own_login_role``: Postgres prüft ``SET ROLE``
gegen den **Sitzungsbenutzer**, nicht gegen die aktuell gesetzte Rolle. Eine
gemeinsame Anmelderolle, die alle Mandantenrollen annehmen darf, lässt daher
aus ``r_alpha`` heraus ein ``SET ROLE r_beta`` zu — nachgemessen, nicht
vermutet. Der Rollenwechsel ist keine Einbahnstrasse, und damit wäre
``SET LOCAL ROLE`` allein keine Grenze gegen SQL-Injection, sondern nur gegen
Anwendungsfehler. Deshalb bekommt jeder Mandant seine **eigene Anmelderolle im
DSN**: dann existiert auf dieser Verbindung überhaupt keine fremde Rolle, in
die man wechseln könnte, und selbst die Metadaten des Nachbarschemas sind
unsichtbar.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.engine import make_url

#: Erlaubte Form eines Slugs. Bewusst eng: aus dem Slug werden Schemaname und
#: Rollenname gebildet, beide gehen unquotiert nicht sicher in SQL.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

#: Erlaubte Form von Schema- und Rollennamen. Dieselbe Enge, plus die
#: Präfixe, die das Runbook vergibt.
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

#: Postgres-Schlüsselwörter, die als Schemaname zwar erlaubt, aber ein
#: Eigentor wären.
RESERVED_SCHEMAS = frozenset({"information_schema", "pg_catalog", "pg_toast"})


class TenantStatus(StrEnum):
    """Lebenszyklus eines Mandanten. Steuert, was die Middleware antwortet."""

    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    OFFBOARDING = "offboarding"

    @property
    def serves_requests(self) -> bool:
        """Nur ein aktiver Mandant wird bedient.

        ``provisioning`` und ``offboarding`` sind Übergänge, in denen Daten
        wandern — eine Anfrage dorthin liest oder schreibt einen halben Zustand.
        """
        return self is TenantStatus.ACTIVE


class TenantConfigError(RuntimeError):
    """Die Registry ist unbrauchbar. Immer fatal beim Start, nie eine Warnung."""


@dataclass(frozen=True, slots=True)
class Tenant:
    """Ein Mandant, wie ihn der Anfragepfad braucht."""

    slug: str
    name: str
    dsn: str
    schema_name: str
    #: ``None`` heisst: kein ``SET LOCAL ROLE``, die Anmelderolle der Verbindung
    #: bleibt stehen. Nur bei genau einem Mandanten zulässig (siehe
    #: ``TenantRegistry._validate``) — dort gibt es nichts, wovon zu trennen wäre.
    db_role: str | None
    #: Alembic-Revision, auf der das Schema steht. Weicht sie von der
    #: Kopf-Version des Codes ab, wird dieser Mandant mit 503 bedient statt mit
    #: möglicherweise falschen Abfragen (ADR-0013 D7).
    schema_version: str
    status: TenantStatus = TenantStatus.ACTIVE
    #: Hostname, unter dem der Mandant erreichbar ist. ``None`` heisst
    #: „jeder Hostname" und ist nur bei genau einem Mandanten zulässig — der
    #: On-prem-Fall, wo der Betreiber den Namen frei wählt (ADR-0013 D8).
    hostname: str | None = None

    @property
    def matches_any_host(self) -> bool:
        return self.hostname is None

    @property
    def expected_session_user(self) -> str | None:
        """Anmeldename, mit dem die Verbindung dieses Mandanten aufgebaut wird.

        Die Zusicherung prüft ihn zusätzlich zu ``current_user``: er lässt sich
        innerhalb der Transaktion nicht ändern und ist damit der härtere Beleg
        dafür, auf wessen Verbindung wir sitzen.
        """
        return dsn_username(self.dsn)


def _require(mapping: Mapping[str, object], key: str, slug: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TenantConfigError(f"Mandant {slug!r}: Feld {key!r} fehlt oder ist leer.")
    return value.strip()


def _check_identifier(value: str, *, field: str, slug: str) -> str:
    if not IDENTIFIER_PATTERN.match(value):
        raise TenantConfigError(
            f"Mandant {slug!r}: {field}={value!r} ist kein zulässiger Bezeichner. "
            "Erlaubt sind Kleinbuchstaben, Ziffern und Unterstrich, beginnend "
            "mit einem Buchstaben — der Wert geht unquotiert in SQL."
        )
    if value in RESERVED_SCHEMAS:
        raise TenantConfigError(f"Mandant {slug!r}: {field}={value!r} ist ein Systemschema.")
    return value


def dsn_username(dsn: str) -> str | None:
    """Anmeldename aus dem DSN, oder ``None`` wenn keiner drinsteht."""
    try:
        return make_url(dsn).username
    except Exception as exc:  # noqa: BLE001 — jeder Parse-Fehler ist derselbe Abbruch
        raise TenantConfigError(f"DSN ist nicht lesbar: {exc}") from None


def _require_own_login_role(tenant: Tenant) -> None:
    """Der Mandant muss sich mit seiner eigenen Rolle anmelden.

    Sonst hängt die Trennung an ``SET LOCAL ROLE``, und das ist gegen einen
    Angreifer mit SQL-Ausführung keine Grenze (siehe Modul-Docstring).
    """
    user = dsn_username(tenant.dsn)
    if not user:
        raise TenantConfigError(
            f"Mandant {tenant.slug!r}: im DSN steht kein Anmeldename. Bei mehreren "
            "Mandanten meldet sich jeder mit seiner eigenen Rolle an — eine "
            "gemeinsame Anmelderolle könnte per SET ROLE in jeden anderen "
            "Mandanten wechseln."
        )
    if user != tenant.db_role:
        raise TenantConfigError(
            f"Mandant {tenant.slug!r}: der DSN meldet sich als {user!r} an, "
            f"db_role ist aber {tenant.db_role!r}. Beide müssen gleich sein: "
            "Postgres prüft SET ROLE gegen den Sitzungsbenutzer, eine gemeinsame "
            "Anmelderolle mit Mitgliedschaft in allen Mandantenrollen kann daher "
            "aus jedem Mandanten in jeden anderen wechseln."
        )


class TenantRegistry:
    """Unveränderliche Sammlung von Mandanten mit Auflösung über den Hostnamen."""

    def __init__(self, tenants: Iterable[Tenant]) -> None:
        self._tenants: tuple[Tenant, ...] = tuple(tenants)
        self._validate()
        self._by_slug = {t.slug: t for t in self._tenants}
        self._by_host = {t.hostname.lower(): t for t in self._tenants if t.hostname}
        self._catch_all = next((t for t in self._tenants if t.matches_any_host), None)

    # -- Validierung ------------------------------------------------------
    def _validate(self) -> None:
        if not self._tenants:
            raise TenantConfigError(
                "Die Mandanten-Registry ist leer. Auch eine Installation mit "
                "genau einem Kunden braucht dessen Zeile (ADR-0013 D8)."
            )
        self._reject_duplicates()
        if len(self._tenants) == 1:
            return
        # Ab zwei Mandanten gibt es etwas zu trennen — und dann ist jede
        # Abkürzung, die bei n=1 harmlos war, eine offene Flanke.
        for tenant in self._tenants:
            if tenant.db_role is None:
                raise TenantConfigError(
                    f"Mandant {tenant.slug!r}: db_role fehlt. Ohne eigene "
                    "Datenbankrolle erzwingt Postgres die Trennung nicht, und "
                    "bei mehr als einem Mandanten ist genau das die Zusage "
                    "(ADR-0013 D1)."
                )
            if tenant.hostname is None:
                raise TenantConfigError(
                    f"Mandant {tenant.slug!r}: hostname fehlt. Ein Auffang-Eintrag "
                    "für jeden Hostnamen ist nur bei genau einem Mandanten "
                    "zulässig, sonst entscheidet die Reihenfolge, wer bedient wird."
                )
            if tenant.schema_name == "public":
                raise TenantConfigError(
                    f"Mandant {tenant.slug!r}: schema_name='public' ist bei mehreren "
                    "Mandanten nicht zulässig — jeder Kunde braucht sein eigenes Schema."
                )
            _require_own_login_role(tenant)

    def _reject_duplicates(self) -> None:
        seen: dict[str, set[str]] = {"slug": set(), "hostname": set(), "role": set()}
        # Schemas kollidieren nur innerhalb derselben Datenbank: zwei Kunden auf
        # getrennten Clustern dürfen beide 't_default' heissen.
        schemas: set[tuple[str, str]] = set()
        for tenant in self._tenants:
            for field, value in (
                ("slug", tenant.slug),
                ("hostname", tenant.hostname.lower() if tenant.hostname else None),
                ("role", tenant.db_role),
            ):
                if value is None:
                    continue
                if value in seen[field]:
                    raise TenantConfigError(f"{field}={value!r} ist doppelt in der Registry.")
                seen[field].add(value)
            login = dsn_username(tenant.dsn)
            if login is not None and len(self._tenants) > 1:
                if login in seen.setdefault("login", set()):
                    raise TenantConfigError(
                        f"Anmelderolle {login!r} wird von mehreren Mandanten benutzt. "
                        "Jeder Mandant braucht seine eigene — sonst kann eine "
                        "Verbindung per SET ROLE in den anderen wechseln."
                    )
                seen["login"].add(login)
            key = (tenant.dsn, tenant.schema_name)
            if key in schemas:
                raise TenantConfigError(
                    f"Schema {tenant.schema_name!r} ist in derselben Datenbank doppelt vergeben."
                )
            schemas.add(key)

    # -- Zugriff ----------------------------------------------------------
    @property
    def tenants(self) -> tuple[Tenant, ...]:
        return self._tenants

    @property
    def is_single_tenant(self) -> bool:
        return len(self._tenants) == 1

    def by_slug(self, slug: str) -> Tenant | None:
        return self._by_slug.get(slug)

    def resolve_host(self, host: str | None) -> Tenant | None:
        """Mandant für einen ``Host``-Header, oder ``None`` bei unbekannt.

        Der Port wird abgeschnitten, Gross-/Kleinschreibung ignoriert. Ein
        exakter Treffer schlägt den Auffang-Eintrag: sonst würde in einer
        On-prem-Installation mit zweitem Mandanten der erste alles schlucken.
        """
        if host:
            normalized = host.split(",")[0].strip().lower()
            # IPv6 in Klammern: "[::1]:8000" -> "[::1]"
            if normalized.startswith("["):
                normalized = normalized.partition("]")[0] + "]"
            else:
                normalized = normalized.rsplit(":", 1)[0] if ":" in normalized else normalized
            hit = self._by_host.get(normalized)
            if hit is not None:
                return hit
        return self._catch_all


def _tenant_from_mapping(raw: Mapping[str, object], *, default_dsn: str) -> Tenant:
    slug_raw = raw.get("slug")
    if not isinstance(slug_raw, str) or not SLUG_PATTERN.match(slug_raw):
        raise TenantConfigError(
            f"slug={slug_raw!r} ist unzulässig. Erlaubt: 2–31 Zeichen, "
            "Kleinbuchstaben/Ziffern/Unterstrich, beginnend mit einem Buchstaben."
        )
    slug = slug_raw

    status_raw = raw.get("status", TenantStatus.ACTIVE.value)
    try:
        status = TenantStatus(str(status_raw))
    except ValueError as exc:
        allowed = ", ".join(s.value for s in TenantStatus)
        raise TenantConfigError(
            f"Mandant {slug!r}: status={status_raw!r} unbekannt. Erlaubt: {allowed}."
        ) from exc

    # Ohne eigenen DSN gilt der der Installation — der Normalfall
    # „alle Kunden im selben Cluster, je ein Schema".
    dsn_raw = raw.get("dsn")
    dsn = dsn_raw.strip() if isinstance(dsn_raw, str) and dsn_raw.strip() else default_dsn
    if not dsn:
        raise TenantConfigError(
            f"Mandant {slug!r}: kein dsn angegeben und MAGISTER_DATABASE_URL ist leer."
        )

    schema_name = _check_identifier(
        str(raw.get("schema_name") or f"t_{slug}"), field="schema_name", slug=slug
    )
    role_raw = raw.get("db_role")
    db_role: str | None = None
    if isinstance(role_raw, str) and role_raw.strip():
        db_role = _check_identifier(role_raw.strip(), field="db_role", slug=slug)

    hostname_raw = raw.get("hostname")
    hostname: str | None = None
    if isinstance(hostname_raw, str) and hostname_raw.strip():
        hostname = hostname_raw.strip().lower()

    return Tenant(
        slug=slug,
        name=_require(raw, "name", slug) if raw.get("name") else slug,
        dsn=dsn,
        schema_name=schema_name,
        db_role=db_role,
        schema_version=str(raw.get("schema_version") or "").strip(),
        status=status,
        hostname=hostname,
    )


def registry_from_json(payload: str, *, default_dsn: str) -> TenantRegistry:
    """Registry aus ``MAGISTER_TENANTS`` lesen (JSON-Liste von Objekten)."""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TenantConfigError(f"MAGISTER_TENANTS ist kein gültiges JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise TenantConfigError("MAGISTER_TENANTS muss eine JSON-Liste von Objekten sein.")
    tenants = []
    for entry in parsed:
        if not isinstance(entry, Mapping):
            raise TenantConfigError(f"MAGISTER_TENANTS: {entry!r} ist kein Objekt.")
        tenants.append(_tenant_from_mapping(entry, default_dsn=default_dsn))
    return TenantRegistry(tenants)


def single_tenant_registry(
    *, dsn: str, slug: str = "default", schema_name: str = "public"
) -> TenantRegistry:
    """Registry mit genau einem Mandanten — der noch nicht umgezogene Bestand.

    Kein Sonderweg im Anfragepfad: derselbe Eintrag, dieselbe Auflösung,
    dieselbe Sitzungs-Einrichtung (ADR-0013 D8). Nur eben ohne eigene Rolle und
    noch auf ``public``, bis der Schema-Umzug gelaufen ist.
    """
    return TenantRegistry(
        [
            Tenant(
                slug=slug,
                name=slug,
                dsn=dsn,
                schema_name=schema_name,
                db_role=None,
                schema_version="",
                status=TenantStatus.ACTIVE,
                hostname=None,
            )
        ]
    )
