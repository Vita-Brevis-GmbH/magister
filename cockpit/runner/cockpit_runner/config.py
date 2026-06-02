from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNNER_", env_file=".env", extra="ignore")

    cockpit_url: str = Field(default="http://localhost:8001")
    cockpit_token: str = Field(default="change-me-in-prod")
    poll_interval_s: int = 30
    ssh_user: str = "magister-ops"
    dry_run: bool = False
    http_timeout_s: float = 10.0


settings = Settings()
