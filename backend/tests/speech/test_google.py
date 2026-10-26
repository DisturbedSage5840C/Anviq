import base64
import json

import httpx
import pytest
import respx

from app.channel.audio import PreparedAudio
from app.speech.base import SpeechProviderError, Voice
from app.speech.google import GoogleSTT, GoogleTTS

STT_URL = "https://stt.test/v1/speech:recognize"
TTS_URL = "https://tts.test/v1/text:synthesize"
KEY = "google-secret-key"
AUDIO = PreparedAudio(wav=b"RIFFfakewav", duration_s=2.0)


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@respx.mock
async def test_transcribe_sends_linear16_and_maps_best_alternative(http) -> None:
    route = respx.post(STT_URL).respond(
        json={"results": [{"alternatives": [{"transcript": "दो अंक", "confidence": 0.91}]}]}
    )
    stt = GoogleSTT(http, api_key=KEY, url=STT_URL, retry_delay_s=0)

    result = await stt.transcribe(AUDIO, lang_hint="hi")

    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == KEY
    body = json.loads(request.content)
    assert body["config"]["languageCode"] == "hi-IN"
    assert body["config"]["encoding"] == "LINEAR16"
    assert body["config"]["sampleRateHertz"] == 16000
    assert base64.b64decode(body["audio"]["content"]) == b"RIFFfakewav"
    assert (result.text, result.language_code, result.confidence) == ("दो अंक", "hi-IN", 0.91)
    assert result.duration_s == 2.0


@respx.mock
async def test_transcribe_without_hint_allows_hindi_and_english(http) -> None:
    route = respx.post(STT_URL).respond(
        json={"results": [{"alternatives": [{"transcript": "ok", "confidence": 0.8}]}]}
    )
    stt = GoogleSTT(http, api_key=KEY, url=STT_URL, retry_delay_s=0)

    await stt.transcribe(AUDIO, lang_hint=None)

    config = json.loads(route.calls.last.request.content)["config"]
    assert config["languageCode"] == "hi-IN"
    assert config["alternativeLanguageCodes"] == ["en-IN"]


@respx.mock
async def test_transcribe_returns_empty_text_for_silence(http) -> None:
    respx.post(STT_URL).respond(json={})
    stt = GoogleSTT(http, api_key=KEY, url=STT_URL, retry_delay_s=0)

    result = await stt.transcribe(AUDIO, lang_hint="hi")

    assert result.text == ""
    assert result.confidence == 0.0


@respx.mock
async def test_transcribe_retries_then_fails_without_leaking_the_key(http) -> None:
    route = respx.post(STT_URL).respond(503)
    stt = GoogleSTT(http, api_key=KEY, url=STT_URL, retry_delay_s=0)

    with pytest.raises(SpeechProviderError) as caught:
        await stt.transcribe(AUDIO, lang_hint="hi")

    assert route.call_count == 3
    assert KEY not in str(caught.value)


@respx.mock
async def test_synthesize_maps_voice_to_neural2_name_pace_and_returns_wav(http) -> None:
    route = respx.post(TTS_URL).respond(json={"audioContent": base64.b64encode(b"RIFF-g").decode()})
    tts = GoogleTTS(http, api_key=KEY, url=TTS_URL, retry_delay_s=0)

    audio = await tts.synthesize("नमस्ते", "hi", Voice(speaker="male", pace=0.9))

    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == KEY
    assert json.loads(request.content) == {
        "input": {"text": "नमस्ते"},
        "voice": {"languageCode": "hi-IN", "name": "hi-IN-Neural2-B", "ssmlGender": "MALE"},
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "speakingRate": 0.9,
            "sampleRateHertz": 24000,
        },
    }
    assert audio == b"RIFF-g"


@respx.mock
@pytest.mark.parametrize(
    ("lang", "speaker", "name"),
    [
        ("hi", "female", "hi-IN-Neural2-A"),
        ("en", "female", "en-IN-Neural2-A"),
        ("en", "male", "en-IN-Neural2-B"),
    ],
)
async def test_synthesize_picks_the_neural2_voice_for_each_language_and_gender(
    http, lang: str, speaker: str, name: str
) -> None:
    route = respx.post(TTS_URL).respond(json={"audioContent": base64.b64encode(b"RIFF-g").decode()})
    tts = GoogleTTS(http, api_key=KEY, url=TTS_URL, retry_delay_s=0)

    await tts.synthesize("hello", lang, Voice(speaker=speaker, pace=1.0))

    assert json.loads(route.calls.last.request.content)["voice"]["name"] == name


@respx.mock
async def test_synthesize_falls_back_to_the_female_voice_for_an_unknown_speaker(http) -> None:
    route = respx.post(TTS_URL).respond(json={"audioContent": base64.b64encode(b"RIFF-g").decode()})
    tts = GoogleTTS(http, api_key=KEY, url=TTS_URL, retry_delay_s=0)

    await tts.synthesize("नमस्ते", "hi", Voice(speaker="priya", pace=1.0))

    assert json.loads(route.calls.last.request.content)["voice"] == {
        "languageCode": "hi-IN",
        "name": "hi-IN-Neural2-A",
        "ssmlGender": "FEMALE",
    }


@respx.mock
async def test_synthesize_fails_without_audio_content(http) -> None:
    respx.post(TTS_URL).respond(json={})
    tts = GoogleTTS(http, api_key=KEY, url=TTS_URL, retry_delay_s=0)

    with pytest.raises(SpeechProviderError):
        await tts.synthesize("नमस्ते", "hi", Voice(speaker="female"))
