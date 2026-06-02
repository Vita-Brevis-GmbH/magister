from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COCKPIT_", env_file=".env", extra="ignore")

    database_url: str = Field(default="postgresql+asyncpg://cockpit:cockpit@localhost:5433/cockpit")
    bootstrap_token: str = Field(default="change-me-in-prod")
    health_poll_interval_s: int = 60
    http_timeout_s: float = 5.0


settings = Settings()
