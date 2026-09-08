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
    published_address: str = Field(default="127.0.0.1:4444")
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
