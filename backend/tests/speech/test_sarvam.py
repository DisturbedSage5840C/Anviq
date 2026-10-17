import base64
import json

import httpx
import pytest
import respx

from app.channel.audio import PreparedAudio
from app.speech.base import SpeechProviderError, SpeechTextTooLongError, Voice
from app.speech.sarvam import SarvamSTT, SarvamTTS

BASE = "https://sarvam.test"
KEY = "sk-sarvam-secret"
AUDIO = PreparedAudio(wav=b"RIFFfakewav", duration_s=3.5)
VOICE = Voice(speaker="priya", pace=1.1)


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def stt(http) -> SarvamSTT:
    return SarvamSTT(http, api_key=KEY, model="saaras:v4", base_url=BASE, retry_delay_s=0)


@pytest.fixture
def tts(http) -> SarvamTTS:
    return SarvamTTS(
        http, api_key=KEY, model="bulbul:v3", sample_rate=24000, base_url=BASE, retry_delay_s=0
    )


@respx.mock
async def test_transcribe_sends_authenticated_multipart_with_model_and_hint(stt) -> None:
    route = respx.post(f"{BASE}/speech-to-text").respond(
        json={"transcript": "दो अंकों का घटाना", "language_code": "hi-IN"}
    )

    result = await stt.transcribe(AUDIO, lang_hint="hi")

    request = route.calls.last.request
    assert request.headers["api-subscription-key"] == KEY
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="model"' in body and b"saaras:v4" in body
    assert b'name="language_code"' in body and b"hi-IN" in body
    assert b'name="file"' in body and b"RIFFfakewav" in body
    assert result.text == "दो अंकों का घटाना"
    assert result.language_code == "hi-IN"
    assert result.duration_s == 3.5


@respx.mock
async def test_transcribe_without_hint_detects_language_and_reports_probability(stt) -> None:
    route = respx.post(f"{BASE}/speech-to-text").respond(
        json={"transcript": "subtraction", "language_code": "en-IN", "language_probability": 0.87}
    )

    result = await stt.transcribe(AUDIO, lang_hint=None)

    assert b'name="language_code"' not in route.calls.last.request.content
    assert result.language_code == "en-IN"
    assert result.confidence == 0.87


@respx.mock
async def test_transcribe_falls_back_to_hint_when_language_not_detected(stt) -> None:
    respx.post(f"{BASE}/speech-to-text").respond(json={"transcript": "हाँ", "language_code": None})

    result = await stt.transcribe(AUDIO, lang_hint="hi")

    assert result.language_code == "hi-IN"
    assert result.confidence is None


@respx.mock
async def test_transcribe_retries_transient_failures(stt) -> None:
    route = respx.post(f"{BASE}/speech-to-text").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429),
            httpx.Response(200, json={"transcript": "ठीक है", "language_code": "hi-IN"}),
        ]
    )

    result = await stt.transcribe(AUDIO, lang_hint="hi")

    assert result.text == "ठीक है"
    assert route.call_count == 3


@respx.mock
async def test_transcribe_gives_up_after_retries_without_leaking_the_key(stt) -> None:
    route = respx.post(f"{BASE}/speech-to-text").respond(503)

    with pytest.raises(SpeechProviderError) as caught:
        await stt.transcribe(AUDIO, lang_hint="hi")

    assert route.call_count == 3
    assert KEY not in str(caught.value)


@respx.mock
async def test_transcribe_does_not_retry_client_errors(stt) -> None:
    route = respx.post(f"{BASE}/speech-to-text").respond(400, json={"error": "bad audio"})

    with pytest.raises(SpeechProviderError):
        await stt.transcribe(AUDIO, lang_hint="hi")

    assert route.call_count == 1


@respx.mock
async def test_transcribe_rejects_unexpected_response_shape(stt) -> None:
    respx.post(f"{BASE}/speech-to-text").respond(json={"unexpected": True})

    with pytest.raises(SpeechProviderError):
        await stt.transcribe(AUDIO, lang_hint="hi")


@respx.mock
async def test_synthesize_posts_configured_model_speaker_and_pace(tts) -> None:
    wav = b"RIFF-synth"
    route = respx.post(f"{BASE}/text-to-speech").respond(
        json={"audios": [base64.b64encode(wav).decode()]}
    )

    audio = await tts.synthesize("रिया, 5 कहाँ से आया?", "hi", VOICE)

    request = route.calls.last.request
    assert request.headers["api-subscription-key"] == KEY
    assert json.loads(request.content) == {
        "text": "रिया, 5 कहाँ से आया?",
        "language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": "priya",
        "pace": 1.1,
        "speech_sample_rate": 24000,
        "output_audio_codec": "wav",
    }
    assert audio == wav


@respx.mock
async def test_synthesize_rejects_text_over_the_model_limit(http) -> None:
    v2 = SarvamTTS(http, api_key=KEY, model="bulbul:v2", base_url=BASE, retry_delay_s=0)
    route = respx.post(f"{BASE}/text-to-speech").respond(json={"audios": []})

    with pytest.raises(SpeechTextTooLongError):
        await v2.synthesize("अ" * 1501, "hi", VOICE)

    assert route.call_count == 0


@respx.mock
async def test_synthesize_fails_when_no_audio_is_returned(tts) -> None:
    respx.post(f"{BASE}/text-to-speech").respond(json={"audios": []})

    with pytest.raises(SpeechProviderError):
        await tts.synthesize("नमस्ते", "hi", VOICE)


@respx.mock
async def test_synthesize_rejects_unsupported_language(tts) -> None:
    with pytest.raises(SpeechProviderError):
        await tts.synthesize("hola", "es", VOICE)
