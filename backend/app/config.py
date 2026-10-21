"""Typed settings. Secrets are validated at startup so a bad deploy fails fast."""

import json
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.privacy.crypto import InvalidKeyError, decode_key

DEPLOYED_ENVS = ("staging", "prod")
MIN_DASHBOARD_TOKEN_CHARS = 24
TWILIO_SID_PATTERN = r"^AC[0-9a-fA-F]{32}$"
TWILIO_FROM_PATTERN = r"^\+\d{8,15}$"
HTTPS_URL_PATTERN = r"^https://[^\s/]+\S*$"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: Literal["local", "staging", "prod"] = "local"

    wa_verify_token: SecretStr
    wa_app_secret: SecretStr
    wa_phone_number_id: str | None = None
    wa_access_token: SecretStr | None = None
    # Meta retires Graph versions on a schedule, so the version is config, not code.
    wa_graph_version: str = Field(default="v25.0", pattern=r"^v\d+\.\d+$")

    # Which WhatsApp channel carries the teachers' messages. Twilio's sandbox is the pilot channel
    # while Meta's business verification is pending; both feed the same pipeline.
    whatsapp_provider: Literal["meta", "twilio"] = "meta"
    twilio_account_sid: str | None = Field(default=None, pattern=TWILIO_SID_PATTERN)
    twilio_auth_token: SecretStr | None = None
    # The number replies come from, e.g. the sandbox's +14155238886.
    twilio_whatsapp_from: str | None = Field(default=None, pattern=TWILIO_FROM_PATTERN)
    # The exact public URL configured in Twilio. Its signature covers this string, and a proxy
    # rewrites the scheme and host, so it cannot be rebuilt from the request.
    twilio_webhook_url: str | None = Field(default=None, pattern=HTTPS_URL_PATTERN)

    database_url: str = "postgresql+asyncpg://anviq:anviq@localhost:5432/anviq"
    redis_url: str = "redis://localhost:6379/0"

    # The mentor dashboard feed. Both must be set or GET /dashboard/trends answers 503. The URL
    # logs in as dashboard_ro (select on public_trends only); the token gates the endpoint.
    dashboard_database_url: SecretStr | None = None
    dashboard_api_token: SecretStr | None = Field(
        default=None, min_length=MIN_DASHBOARD_TOKEN_CHARS
    )

    # Demo mode (plan D10): when set, a "14-day" mirror cycle lasts this many minutes so a judge can
    # watch Day 1 to Day 14 in one sitting. Unset in production.
    demo_cycle_minutes: int | None = Field(default=None, gt=0)

    # Slack-style incoming webhook for the daily cost report. Unset: the report is only logged.
    ops_webhook_url: SecretStr | None = None

    # Error reporting stays off without a DSN. Events are PII-scrubbed in app.ops.sentry.
    sentry_dsn: SecretStr | None = None

    # base64 of 32 random bytes each; generate with `openssl rand -base64 32`.
    field_key: SecretStr | None = None
    phone_pepper: SecretStr | None = None

    anthropic_api_key: SecretStr | None = None
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    model_offline: str = "claude-opus-5-5"
    # Ask Anviq scope gate (plan 4.8, tau): the weakest full-text match still treated as covered.
    # A starting guess; tune it on eval/datasets/ask_*.jsonl with app.evaluation.citations.
    ask_min_score: float = Field(default=0.05, ge=0, le=1)

    # Paid model steps (Plan, Reflect, Ask, Mirror, each practice turn) one teacher may use a day.
    max_model_steps_per_day: int = Field(default=60, gt=0)

    # Vendors rename and retire models, so model ids are config, not code.
    sarvam_api_key: SecretStr | None = None
    google_speech_api_key: SecretStr | None = None
    stt_provider: Literal["sarvam", "google"] = "sarvam"
    tts_provider: Literal["sarvam", "google"] = "sarvam"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_sample_rate: int = 24000

    @field_validator("whatsapp_provider", mode="before")
    @classmethod
    def _provider_name_is_forgiving(cls, raw: object) -> object:
        # Compose passes the variable empty when unset; "Twilio " should not crash-loop the API.
        if not isinstance(raw, str):
            return raw
        return raw.strip().lower() or "meta"

    @field_validator(
        "twilio_account_sid",
        "twilio_auth_token",
        "twilio_whatsapp_from",
        "twilio_webhook_url",
        mode="before",
    )
    @classmethod
    def _blank_twilio_value_is_unset(cls, raw: object) -> object:
        # Compose passes every listed variable, empty when the host has not set it.
        return None if isinstance(raw, str) and not raw.strip() else raw

    @computed_field  # type: ignore[prop-decorator]
    @property
    def wa_graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.wa_graph_version}"

    @model_validator(mode="after")
    def require_twilio_settings(self) -> Self:
        if self.whatsapp_provider != "twilio":
            return self
        missing = [
            name
            for name, value in (
                ("TWILIO_ACCOUNT_SID", self.twilio_account_sid),
                ("TWILIO_AUTH_TOKEN", self.twilio_auth_token),
                ("TWILIO_WHATSAPP_FROM", self.twilio_whatsapp_from),
                ("TWILIO_WEBHOOK_URL", self.twilio_webhook_url),
            )
            if value is None
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} required when WHATSAPP_PROVIDER=twilio")
        return self

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


class WebRoomSettings(BaseSettings):
    """Just the browser origins allowed to call /web/turn, readable before full Settings load.

    `create_app()` runs at import time, so CORS cannot wait for the required webhook secrets.
    WEB_ALLOWED_ORIGINS is a JSON list or comma-separated, e.g. https://anviq-demo.vercel.app.
    Empty: no CORS. It is read at import, so a malformed value must never stop the API starting.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    web_allowed_origins: Annotated[list[str], NoDecode] = []

    @field_validator("web_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, raw: object) -> object:
        if not isinstance(raw, str):
            return raw
        if raw.lstrip().startswith("["):
            try:
                return [str(origin).rstrip("/") for origin in json.loads(raw)]
            except ValueError:
                pass  # not valid JSON: read it as a list anyway rather than stop the API starting
        return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
