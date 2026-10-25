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
# (Sarvam pay-as-you-go: Rs 29.40 per hour of audio, rounded up to 30, and Rs 30 per 10,000
# characters for Bulbul V3, checked on sarvam.ai/api-pricing on 2026-10-25; Google at 84 INR/USD,
# not re-checked). Volume plans and Bulbul V4 Flash (Rs 10 per 10,000) would be cheaper.
_INR_PER_STT_SECOND = {"sarvam": Decimal(30) / 3600, "google": Decimal("0.0224")}
_INR_PER_TTS_CHAR = {"sarvam": Decimal(30) / 10_000, "google": Decimal("0.001344")}
_INR_PLACES = Decimal("0.0001")  # speech_usage.est_cost_inr is numeric(10, 4)
SINK_TIMEOUT_S = 2.0  # a slow database must not hold up a teacher's reply


@dataclass(frozen=True)
class SpeechUsage:
    provider: str
    kind: SpeechKind
    amount: Decimal  # seconds of audio for stt, characters for tts
    est_cost_inr: Decimal


class SpeechUsageSink(Protocol):
    async def record(self, usage: SpeechUsage) -> None: ...


def stt_cost_inr(provider: str, seconds: Decimal) -> Decimal:
    """Zero for a provider with no known rate: an unpriced call is better shown than invented."""
    return (seconds * _INR_PER_STT_SECOND.get(provider, Decimal(0))).quantize(_INR_PLACES)


def tts_cost_inr(provider: str, characters: int) -> Decimal:
    return (characters * _INR_PER_TTS_CHAR.get(provider, Decimal(0))).quantize(_INR_PLACES)


async def _record_quietly(sink: SpeechUsageSink, usage: SpeechUsage) -> None:
    try:
        await asyncio.wait_for(sink.record(usage), timeout=SINK_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - bookkeeping must not break a reply
        logger.warning("could not record speech usage", exc_info=True)


class MeteredSTT:
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
    def __init__(self, inner: TTSProvider, sink: SpeechUsageSink, *, provider: str) -> None:
        self._inner = inner
        self._sink = sink
        self._provider = provider

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        wav = await self._inner.synthesize(text, lang, voice)
        usage = SpeechUsage(
            self._provider, "tts", Decimal(len(text)), tts_cost_inr(self._provider, len(text))
        )
        await _record_quietly(self._sink, usage)
        return wav
