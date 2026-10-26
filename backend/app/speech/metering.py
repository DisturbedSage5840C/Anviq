"""Speech spend, recorded where the vendor is called so the cost report is complete.

Wrapping the providers (not the pipeline) covers the WhatsApp path and the web room alike. Only
the amount billed (seconds of audio, characters spoken) and its estimated cost are kept; the audio
and the text never reach the sink. A failed call costs nothing and a sink failure is logged and
swallowed, because bookkeeping must never cost a teacher their reply.
"""

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from app.channel.audio import PreparedAudio
from app.speech.base import STTProvider, Transcript, TTSProvider, Voice

logger = logging.getLogger(__name__)

SpeechKind = Literal["stt", "tts"]

# Estimated rupees per second of audio transcribed / per character spoken. These are list prices
# (Sarvam pay-as-you-go: Rs 29.40 per hour of audio, rounded up to 30, and per 10,000 characters
# Rs 30 for Bulbul V3 and Rs 10 for Bulbul V4 Flash, checked on sarvam.ai/api-pricing on
# 2026-10-26; Google at 84 INR/USD, not re-checked). Volume plans would be cheaper.
_INR_PER_STT_SECOND = {"sarvam": Decimal(30) / 3600, "google": Decimal("0.0224")}
_INR_PER_TTS_CHAR = {"sarvam": Decimal(30) / 10_000, "google": Decimal("0.001344")}
# A model with its own rate; any other model is costed at its provider's default above.
_INR_PER_TTS_CHAR_BY_MODEL = {("sarvam", "bulbul:v4-flash"): Decimal(10) / 10_000}
_INR_PLACES = Decimal("0.0001")  # speech_usage.est_cost_inr is numeric(10, 4)
SINK_TIMEOUT_S = 2.0  # a slow database must not hold up a teacher's reply


@dataclass(frozen=True)
class SpeechUsage:
    provider: str
    kind: SpeechKind
    amount: Decimal  # seconds of audio for stt, characters for tts
    est_cost_inr: Decimal


class SpeechUsageSink(Protocol):
    async def record(self, usage: SpeechUsage) -> None:
        """Store one billed call; the amount and cost only, never the audio or the text."""


def stt_cost_inr(provider: str, seconds: Decimal) -> Decimal:
    """Zero for a provider with no known rate: an unpriced call is better shown than invented."""
    return (seconds * _INR_PER_STT_SECOND.get(provider, Decimal(0))).quantize(_INR_PLACES)


def tts_cost_inr(provider: str, characters: int, model: str | None = None) -> Decimal:
    """Rupees for `characters` spoken; the model's own rate if it has one, else the provider's."""
    default = _INR_PER_TTS_CHAR.get(provider, Decimal(0))
    rate = _INR_PER_TTS_CHAR_BY_MODEL.get((provider, model or ""), default)
    return (characters * rate).quantize(_INR_PLACES)


async def _record_quietly(sink: SpeechUsageSink, usage: SpeechUsage) -> None:
    try:
        await asyncio.wait_for(sink.record(usage), timeout=SINK_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - bookkeeping must not break a reply
        logger.warning("could not record speech usage", exc_info=True)


class MeteredSTT:
    """An STT provider that records the seconds of audio each successful call transcribed."""

    def __init__(self, inner: STTProvider, sink: SpeechUsageSink, *, provider: str) -> None:
        self._inner = inner
        self._sink = sink
        self._provider = provider

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        transcript = await self._inner.transcribe(audio, lang_hint=lang_hint)
        seconds = Decimal(str(audio.duration_s))
        usage = SpeechUsage(self._provider, "stt", seconds, stt_cost_inr(self._provider, seconds))
        await _record_quietly(self._sink, usage)
        return transcript


class MeteredTTS:
    """A TTS provider that records the characters each successful call spoke, priced by model."""

    def __init__(
        self,
        inner: TTSProvider,
        sink: SpeechUsageSink,
        *,
        provider: str,
        model: str | None = None,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._provider = provider
        self._model = model

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        wav = await self._inner.synthesize(text, lang, voice)
        cost = tts_cost_inr(self._provider, len(text), self._model)
        usage = SpeechUsage(self._provider, "tts", Decimal(len(text)), cost)
        await _record_quietly(self._sink, usage)
        return wav
