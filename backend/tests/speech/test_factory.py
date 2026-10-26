import base64

import httpx
import pytest

from app.config import Settings
from app.speech.base import Voice
from app.speech.factory import build_speech
from app.speech.google import GoogleSTT, GoogleTTS
from app.speech.metering import MeteredSTT, MeteredTTS, SpeechUsage
from app.speech.sarvam import SarvamSTT, SarvamTTS

BASE = {"app_env": "local", "wa_verify_token": "v", "wa_app_secret": "s", "_env_file": None}


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


def test_no_keys_means_no_speech_providers(http) -> None:
    assert build_speech(Settings(**BASE), http) == (None, None)


def test_sarvam_is_the_default_provider(http) -> None:
    stt, tts = build_speech(Settings(**BASE, sarvam_api_key="k"), http)
    assert isinstance(stt, SarvamSTT) and isinstance(tts, SarvamTTS)


def test_a_usage_sink_wraps_the_providers_so_their_spend_is_recorded(http) -> None:
    class Sink:
        async def record(self, usage: SpeechUsage) -> None: ...

    stt, tts = build_speech(Settings(**BASE, sarvam_api_key="k"), http, Sink())
    assert isinstance(stt, MeteredSTT) and isinstance(tts, MeteredTTS)


@pytest.mark.parametrize(
    ("model", "expected_inr"), [("bulbul:v3", "3.0000"), ("bulbul:v4-flash", "1.0000")]
)
async def test_spend_is_priced_at_the_configured_sarvam_voice_model(
    model: str, expected_inr: str
) -> None:
    rows: list[SpeechUsage] = []

    class Sink:
        async def record(self, usage: SpeechUsage) -> None:
            rows.append(usage)

    audio = base64.b64encode(b"wav").decode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"audios": [audio]}))
    async with httpx.AsyncClient(transport=transport) as client:
        settings = Settings(**BASE, sarvam_api_key="k", sarvam_tts_model=model)
        _, tts = build_speech(settings, client, Sink())
        assert tts is not None
        await tts.synthesize("a" * 1000, "en", Voice("priya"))

    assert [str(r.est_cost_inr) for r in rows] == [expected_inr]


def test_no_sink_means_the_bare_providers(http) -> None:
    stt, tts = build_speech(Settings(**BASE, sarvam_api_key="k"), http, None)
    assert not isinstance(stt, MeteredSTT) and not isinstance(tts, MeteredTTS)


def test_providers_can_be_chosen_independently(http) -> None:
    settings = Settings(
        **BASE,
        sarvam_api_key="k",
        google_speech_api_key="g",
        stt_provider="google",
        tts_provider="sarvam",
    )
    stt, tts = build_speech(settings, http)
    assert isinstance(stt, GoogleSTT) and isinstance(tts, SarvamTTS)
    stt, tts = build_speech(
        settings.model_copy(update={"stt_provider": "sarvam", "tts_provider": "google"}), http
    )
    assert isinstance(stt, SarvamSTT) and isinstance(tts, GoogleTTS)


def test_selected_provider_without_its_key_is_not_built(http) -> None:
    stt, tts = build_speech(Settings(**BASE, google_speech_api_key="g"), http)
    assert (stt, tts) == (None, None)


def test_deployed_env_requires_the_selected_provider_key() -> None:
    key = base64.b64encode(bytes(range(32))).decode()
    deployed = {
        "app_env": "prod",
        "wa_verify_token": "v",
        "wa_app_secret": "s",
        "anthropic_api_key": "k",
        "field_key": key,
        "phone_pepper": key,
        "_env_file": None,
    }
    with pytest.raises(ValueError, match="SARVAM_API_KEY"):
        Settings(**deployed)
    with pytest.raises(ValueError, match="GOOGLE_SPEECH_API_KEY"):
        Settings(**deployed, sarvam_api_key="k", stt_provider="google")
    assert Settings(**deployed, sarvam_api_key="k").stt_provider == "sarvam"
