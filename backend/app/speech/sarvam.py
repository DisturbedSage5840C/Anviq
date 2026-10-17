"""Sarvam AI speech adapters (India-hosted). Model and speaker are config, not code."""

import base64

import httpx

from app.channel.audio import PreparedAudio
from app.speech.base import SpeechProviderError, SpeechTextTooLongError, Transcript, Voice
from app.speech.http import DEFAULT_RETRY_DELAY_S, VendorHttp

SARVAM_BASE_URL = "https://api.sarvam.ai"
LANGUAGE_CODES = {"hi": "hi-IN", "en": "en-IN"}
# Per-request character limits documented for each Bulbul model.
TTS_MAX_CHARS = {"bulbul:v2": 1500, "bulbul:v3": 2500, "bulbul:v4-flash": 2500}
DEFAULT_TTS_MAX_CHARS = 1500


def _language_code(lang: str) -> str:
    try:
        return LANGUAGE_CODES[lang]
    except KeyError:
        raise SpeechProviderError(f"Unsupported language: {lang!r}") from None


class SarvamSTT:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        model: str = "saaras:v4",
        base_url: str = SARVAM_BASE_URL,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._client = VendorHttp(
            http,
            vendor="Sarvam",
            auth_headers={"api-subscription-key": api_key},
            retry_delay_s=retry_delay_s,
        )
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        data = {"model": self._model}
        hint_code = _language_code(lang_hint) if lang_hint else None
        if hint_code:
            data["language_code"] = hint_code
        body = await self._client.post(
            f"{self._base_url}/speech-to-text",
            data=data,
            files={"file": ("voice.wav", audio.wav, "audio/wav")},
        )
        text = body.get("transcript")
        if not isinstance(text, str):
            raise SpeechProviderError("Sarvam STT response had no transcript")
        detected = body.get("language_code")
        probability = body.get("language_probability")
        return Transcript(
            text=text.strip(),
            language_code=detected if isinstance(detected, str) else (hint_code or "unknown"),
            confidence=float(probability) if isinstance(probability, int | float) else None,
            duration_s=audio.duration_s,
        )


class SarvamTTS:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        model: str = "bulbul:v3",
        sample_rate: int = 24000,
        base_url: str = SARVAM_BASE_URL,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._client = VendorHttp(
            http,
            vendor="Sarvam",
            auth_headers={"api-subscription-key": api_key},
            retry_delay_s=retry_delay_s,
        )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._sample_rate = sample_rate

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        limit = TTS_MAX_CHARS.get(self._model, DEFAULT_TTS_MAX_CHARS)
        if len(text) > limit:
            raise SpeechTextTooLongError(f"Text is {len(text)} chars; {self._model} allows {limit}")
        body = await self._client.post(
            f"{self._base_url}/text-to-speech",
            json={
                "text": text,
                "language_code": _language_code(lang),
                "model": self._model,
                "speaker": voice.speaker,
                "pace": voice.pace,
                "speech_sample_rate": self._sample_rate,
                "output_audio_codec": "wav",
            },
        )
        audios = body.get("audios")
        if not isinstance(audios, list) or not audios or not isinstance(audios[0], str):
            raise SpeechProviderError("Sarvam TTS returned no audio")
        try:
            return base64.b64decode(audios[0], validate=True)
        except ValueError:
            raise SpeechProviderError("Sarvam TTS returned invalid audio encoding") from None
