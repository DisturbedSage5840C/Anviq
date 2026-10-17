"""Provider-neutral speech types, so STT/TTS vendors can be swapped via config."""

from dataclasses import dataclass
from typing import Protocol

from app.channel.audio import PreparedAudio


class SpeechProviderError(Exception):
    """A speech provider failed. Messages never contain credentials or audio."""


class SpeechTextTooLongError(SpeechProviderError):
    """Text exceeds what the TTS model accepts in a single request."""


@dataclass(frozen=True)
class Transcript:
    text: str
    language_code: str
    confidence: float | None
    duration_s: float


@dataclass(frozen=True)
class Voice:
    speaker: str
    pace: float = 1.0


class STTProvider(Protocol):
    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        """Return WAV bytes."""
        ...
