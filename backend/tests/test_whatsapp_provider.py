from typing import Any

import httpx
import pytest

from app import worker
from app.channel.evolution_client import EvolutionWhatsAppClient
from app.channel.twilio_client import TwilioWhatsAppClient
from app.channel.whatsapp_client import WhatsAppClient
from app.config import Settings
from app.core.dialogue import EchoBrain
from app.resources import build_whatsapp

SID = "AC" + "2" * 32
TWILIO = {
    "whatsapp_provider": "twilio",
    "twilio_account_sid": SID,
    "twilio_auth_token": "twilio-auth-token-value",
    "twilio_whatsapp_from": "+14155238886",
    "twilio_webhook_url": "https://demo.example.test/webhook/twilio",
}
EVOLUTION = {
    "whatsapp_provider": "evolution",
    "evolution_base_url": "http://evolution:8080",
    "evolution_api_key": "evolution-global-api-key-value",
    "evolution_instance": "anviq-demo",
    "evolution_webhook_secret": "evolution-webhook-secret-0123456789",
}


def _settings(**overrides: str) -> Settings:
    return Settings(
        app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None, **overrides
    )


@pytest.fixture
async def http() -> Any:
    async with httpx.AsyncClient() as client:
        yield client


async def test_meta_without_credentials_has_no_client(http: httpx.AsyncClient) -> None:
    assert build_whatsapp(_settings(), http) is None


async def test_meta_with_credentials_builds_the_cloud_api_client(http: httpx.AsyncClient) -> None:
    settings = _settings(wa_phone_number_id="123", wa_access_token="tok")

    assert isinstance(build_whatsapp(settings, http), WhatsAppClient)


async def test_twilio_builds_the_twilio_client_even_when_meta_credentials_are_set(
    http: httpx.AsyncClient,
) -> None:
    settings = _settings(wa_phone_number_id="123", wa_access_token="tok", **TWILIO)

    assert isinstance(build_whatsapp(settings, http), TwilioWhatsAppClient)


async def test_evolution_builds_the_evolution_client_even_when_meta_credentials_are_set(
    http: httpx.AsyncClient,
) -> None:
    settings = _settings(wa_phone_number_id="123", wa_access_token="tok", **EVOLUTION)

    assert isinstance(build_whatsapp(settings, http), EvolutionWhatsAppClient)


def _capture_pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_pipeline(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(worker, "InboundPipeline", fake_pipeline)
    return captured


def test_the_twilio_pipeline_sends_text_only_because_the_sandbox_cannot_send_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_pipeline(monkeypatch)
    tts = object()
    resources: Any = type("R", (), {"whatsapp": object(), "stt": None, "tts": tts})()

    worker.build_pipeline(resources, _settings(**TWILIO), brain=EchoBrain())

    assert captured["tts"] is None


def test_the_meta_pipeline_keeps_the_configured_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_pipeline(monkeypatch)
    tts = object()
    resources: Any = type("R", (), {"whatsapp": object(), "stt": None, "tts": tts})()

    worker.build_pipeline(resources, _settings(), brain=EchoBrain())

    assert captured["tts"] is tts


def test_the_evolution_pipeline_keeps_the_configured_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_pipeline(monkeypatch)
    tts = object()
    resources: Any = type("R", (), {"whatsapp": object(), "stt": None, "tts": tts})()

    worker.build_pipeline(resources, _settings(**EVOLUTION), brain=EchoBrain())

    assert captured["tts"] is tts


def test_build_pipeline_names_the_missing_evolution_client() -> None:
    resources: Any = type("R", (), {"whatsapp": None, "stt": None, "tts": None})()

    with pytest.raises(RuntimeError, match="EVOLUTION_BASE_URL"):
        worker.build_pipeline(resources, _settings(**EVOLUTION), brain=EchoBrain())


def test_build_pipeline_names_the_missing_twilio_client(monkeypatch: pytest.MonkeyPatch) -> None:
    resources: Any = type("R", (), {"whatsapp": None, "stt": None, "tts": None})()

    with pytest.raises(RuntimeError, match="TWILIO_ACCOUNT_SID"):
        worker.build_pipeline(resources, _settings(**TWILIO), brain=EchoBrain())
