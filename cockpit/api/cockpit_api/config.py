from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COCKPIT_", env_file=".env", extra="ignore")

    database_url: str = Field(default="postgresql+asyncpg://cockpit:cockpit@localhost:5433/cockpit")
    bootstrap_token: str = Field(default="change-me-in-prod")

    # --- Management listener (ADR-0015 D1) ---------------------------------
    # The console must not be reachable from the internet. ``published_address``
    # is what the compose port mapping publishes; a wildcard here aborts the
    # start. ``management_marker`` is the shared value the management site block
    # of the reverse proxy sets on every forwarded request — the application
    # refuses anything without it.
    require_management_listener: bool = Field(default=True)
    management_marker: str = Field(default="")
    #: Marker des Connector-Listeners (TCP 46200, ADR-0014). Muss sich vom
    #: Management-Marker unterscheiden, sonst gilt jeder auf beiden Kanälen.
    connector_marker: str = Field(default="")
    published_address: str = Field(default="127.0.0.1:4444")
    # --- Mandanten-Bereitstellung (ADR-0013 D2) ---------------------------
    # Verwaltungszugang in den Magister-Cluster: eine Rolle mit CREATEROLE und
    # CREATE auf der Datenbank. NICHT eine Mandantenrolle. Ohne diesen Wert
    # kann die Konsole Kunden verwalten, aber keinen bereitstellen.
    tenant_admin_dsn: str = Field(default="")
    # Verzeichnis der Datenebene (apps/api) für ``alembic upgrade head``.
    magister_api_dir: str = Field(default="")
    # Schema mit den Erweiterungen (pgcrypto) im Magister-Cluster.
    tenant_extension_schema: str = Field(default="public")
    # Kopf-Revision, auf die ein neu bereitgestellter Kunde gesetzt wird.
    # Muss zu magister_api.tenancy.version.HEAD_REVISION passen; ein Test in
    # der Datenebene hält die Konstante am echten Alembic-Kopf.
    expected_schema_version: str = Field(default="")
    # --- Connector-Agenten (ADR-0014) -------------------------------------
    # Das Intermediate Connector auf dem Plattform-Server. Der Root bleibt
    # offline (docs/runbooks/platform-ca.md). Ohne diese zwei Werte kann kein
    # Agent angemeldet werden.
    connector_ca_cert: str = Field(default="")
    connector_ca_key: str = Field(default="")
    # Header, unter dem der Reverse Proxy das verifizierte Client-Zertifikat
    # weitergibt. Caddy: {http.request.tls.client.certificate_pem}.
    connector_client_cert_header: str = Field(default="x-connector-client-cert")
    # Wie lange ein Long-Poll offen bleibt, bevor er leer zurückkommt.
    connector_poll_seconds: int = Field(default=25, ge=1, le=110)

    # Vorlage für den DSN-Verweis eines neuen Kunden. Die Konsole speichert
    # NUR diesen Verweis, nie den DSN mit Passwort.
    dsn_ref_template: str = Field(default="tenant_{slug}")

    health_poll_interval_s: int = 60
    release_poll_interval_s: int = 300
    http_timeout_s: float = 5.0
    release_manifest_url_stable: str = Field(
        default="https://releases.vitabrevis.ch/magister-stable.json"
    )
    release_manifest_url_latest: str = Field(
        default="https://releases.vitabrevis.ch/magister-latest.json"
    )


settings = Settings()
