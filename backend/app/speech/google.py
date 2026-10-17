"""Google Cloud Speech adapters, used as the benchmark baseline and the STT/TTS fallback.

Plain REST with an API key header, so no Google client library or service-account file is
needed. Select with STT_PROVIDER=google / TTS_PROVIDER=google.
"""

import base64

import httpx

from app.channel.audio import STT_SAMPLE_RATE, PreparedAudio
from app.speech.base import SpeechProviderError, Transcript, Voice
from app.speech.http import DEFAULT_RETRY_DELAY_S, VendorHttp

STT_URL = "https://speech.googleapis.com/v1/speech:recognize"
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
LANGUAGE_CODES = {"hi": "hi-IN", "en": "en-IN"}
GENDERS = {"female": "FEMALE", "male": "MALE"}
TTS_SAMPLE_RATE = 24000


def _http(http: httpx.AsyncClient, api_key: str, retry_delay_s: float) -> VendorHttp:
    return VendorHttp(
        http,
        vendor="Google",
        auth_headers={"x-goog-api-key": api_key},
        retry_delay_s=retry_delay_s,
    )


def _language_code(lang: str) -> str:
    try:
        return LANGUAGE_CODES[lang]
    except KeyError:
        raise SpeechProviderError(f"Unsupported language: {lang!r}") from None


class GoogleSTT:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        url: str = STT_URL,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._client = _http(http, api_key, retry_delay_s)
        self._url = url

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        language_code = _language_code(lang_hint or "hi")
        config: dict[str, object] = {
            "encoding": "LINEAR16",
            "sampleRateHertz": STT_SAMPLE_RATE,
            "languageCode": language_code,
            "enableAutomaticPunctuation": True,
        }
        if lang_hint is None:
            # Teachers code-mix; without a hint let Google also consider Indian English.
            config["alternativeLanguageCodes"] = ["en-IN"]
        body = await self._client.post(
            self._url,
            json={"config": config, "audio": {"content": base64.b64encode(audio.wav).decode()}},
        )
        text, confidence = _best_alternative(body)
        return Transcript(
            text=text,
            language_code=language_code,
            confidence=confidence,
            duration_s=audio.duration_s,
        )


def _best_alternative(body: dict[str, object]) -> tuple[str, float]:
    results = body.get("results")
    if not isinstance(results, list) or not results:
        return "", 0.0
    alternatives = results[0].get("alternatives") if isinstance(results[0], dict) else None
    if not isinstance(alternatives, list) or not alternatives:
        return "", 0.0
    best = alternatives[0]
    text = best.get("transcript") if isinstance(best, dict) else None
    confidence = best.get("confidence") if isinstance(best, dict) else None
    if not isinstance(text, str):
        raise SpeechProviderError("Google STT response had no transcript")
    return text.strip(), float(confidence) if isinstance(confidence, int | float) else 0.0


class GoogleTTS:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        url: str = TTS_URL,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._client = _http(http, api_key, retry_delay_s)
        self._url = url

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        body = await self._client.post(
            self._url,
            json={
                "input": {"text": text},
                "voice": {
                    "languageCode": _language_code(lang),
                    "ssmlGender": GENDERS.get(voice.speaker, "FEMALE"),
                },
                "audioConfig": {
                    "audioEncoding": "LINEAR16",
                    "speakingRate": voice.pace,
                    "sampleRateHertz": TTS_SAMPLE_RATE,
                },
            },
        )
        content = body.get("audioContent")
        if not isinstance(content, str) or not content:
            raise SpeechProviderError("Google TTS returned no audio")
        try:
            return base64.b64decode(content, validate=True)
        except ValueError:
            raise SpeechProviderError("Google TTS returned invalid audio encoding") from None
