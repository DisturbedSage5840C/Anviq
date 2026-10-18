"""Typed settings. Secrets are validated at startup so a bad deploy fails fast."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.privacy.crypto import InvalidKeyError, decode_key

DEPLOYED_ENVS = ("staging", "prod")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: Literal["local", "staging", "prod"] = "local"

    wa_verify_token: SecretStr
    wa_app_secret: SecretStr
    wa_phone_number_id: str | None = None
    wa_access_token: SecretStr | None = None
    # Meta retires Graph versions on a schedule, so the version is config, not code.
    wa_graph_version: str = Field(default="v25.0", pattern=r"^v\d+\.\d+$")

    database_url: str = "postgresql+asyncpg://anviq:anviq@localhost:5432/anviq"
    redis_url: str = "redis://localhost:6379/0"

    # Slack-style incoming webhook for the daily cost report. Unset: the report is only logged.
    ops_webhook_url: SecretStr | None = None

    # base64 of 32 random bytes each; generate with `openssl rand -base64 32`.
    field_key: SecretStr | None = None
    phone_pepper: SecretStr | None = None

    anthropic_api_key: SecretStr | None = None
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    model_offline: str = "claude-opus-5-5"

    # Vendors rename and retire models, so model ids are config, not code.
    sarvam_api_key: SecretStr | None = None
    google_speech_api_key: SecretStr | None = None
    stt_provider: Literal["sarvam", "google"] = "sarvam"
    tts_provider: Literal["sarvam", "google"] = "sarvam"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_sample_rate: int = 24000

    @computed_field  # type: ignore[prop-decorator]
    @property
    def wa_graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.wa_graph_version}"

    @model_validator(mode="after")
    def require_deployed_secrets(self) -> Self:
        if self.app_env in DEPLOYED_ENVS:
            if self.anthropic_api_key is None:
                raise ValueError(f"ANTHROPIC_API_KEY is required when APP_ENV={self.app_env}")
            for name, secret in (
                ("FIELD_KEY", self.field_key),
                ("PHONE_PEPPER", self.phone_pepper),
            ):
                if secret is None:
                    raise ValueError(f"{name} is required when APP_ENV={self.app_env}")
            self._require_speech_keys()
        return self

    def _require_speech_keys(self) -> None:
        providers = {self.stt_provider, self.tts_provider}
        if "sarvam" in providers and self.sarvam_api_key is None:
            raise ValueError(f"SARVAM_API_KEY is required when APP_ENV={self.app_env}")
        if "google" in providers and self.google_speech_api_key is None:
            raise ValueError(f"GOOGLE_SPEECH_API_KEY is required when APP_ENV={self.app_env}")

    @model_validator(mode="after")
    def validate_key_material(self) -> Self:
        for name, secret in (("FIELD_KEY", self.field_key), ("PHONE_PEPPER", self.phone_pepper)):
            if secret is None:
                continue
            try:
                decode_key(secret.get_secret_value())
            except InvalidKeyError as exc:
                raise ValueError(f"{name} is invalid: {exc}") from None
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
