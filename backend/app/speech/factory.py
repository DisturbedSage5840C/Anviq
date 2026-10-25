"""Builds the configured STT/TTS providers; an unconfigured provider comes back as None."""

import httpx

from app.config import Settings
from app.speech.base import STTProvider, TTSProvider
from app.speech.google import GoogleSTT, GoogleTTS
from app.speech.metering import MeteredSTT, MeteredTTS, SpeechUsageSink
from app.speech.sarvam import SarvamSTT, SarvamTTS


def build_speech(
    settings: Settings, http: httpx.AsyncClient, sink: SpeechUsageSink | None = None
) -> tuple[STTProvider | None, TTSProvider | None]:
    """The configured providers; with a sink, each call's billed amount is recorded."""
    stt, tts = _build_stt(settings, http), _build_tts(settings, http)
    if sink is not None:
        if stt is not None:
            stt = MeteredSTT(stt, sink, provider=settings.stt_provider)
        if tts is not None:
            tts = MeteredTTS(tts, sink, provider=settings.tts_provider)
    return stt, tts


def _build_stt(settings: Settings, http: httpx.AsyncClient) -> STTProvider | None:
    if settings.stt_provider == "google":
        if settings.google_speech_api_key is None:
            return None
        return GoogleSTT(http, api_key=settings.google_speech_api_key.get_secret_value())
    if settings.sarvam_api_key is None:
        return None
    return SarvamSTT(
        http,
        api_key=settings.sarvam_api_key.get_secret_value(),
        model=settings.sarvam_stt_model,
    )


def _build_tts(settings: Settings, http: httpx.AsyncClient) -> TTSProvider | None:
    if settings.tts_provider == "google":
        if settings.google_speech_api_key is None:
            return None
        return GoogleTTS(http, api_key=settings.google_speech_api_key.get_secret_value())
    if settings.sarvam_api_key is None:
        return None
    return SarvamTTS(
        http,
        api_key=settings.sarvam_api_key.get_secret_value(),
        model=settings.sarvam_tts_model,
        sample_rate=settings.sarvam_tts_sample_rate,
    )
