"""Typed settings. Secrets are validated at startup so a bad deploy fails fast."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEPLOYED_ENVS = ("staging", "prod")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: Literal["local", "staging", "prod"] = "local"

    wa_verify_token: SecretStr
    wa_app_secret: SecretStr
    wa_phone_number_id: str | None = None
    wa_access_token: SecretStr | None = None

    database_url: str = "postgresql+asyncpg://anviq:anviq@localhost:5432/anviq"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: SecretStr | None = None
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    model_offline: str = "claude-opus-5-5"

    @model_validator(mode="after")
    def require_deployed_secrets(self) -> Self:
        if self.app_env in DEPLOYED_ENVS and self.anthropic_api_key is None:
            raise ValueError(f"ANTHROPIC_API_KEY is required when APP_ENV={self.app_env}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
