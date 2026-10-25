from decimal import Decimal

import pytest

from app.channel.audio import PreparedAudio
from app.speech.base import SpeechProviderError, Transcript, Voice
from app.speech.metering import (
    MeteredSTT,
    MeteredTTS,
    SpeechUsage,
    stt_cost_inr,
    tts_cost_inr,
)

AUDIO = PreparedAudio(wav=b"w", duration_s=12.5)
VOICE = Voice("speaker")


class Sink:
    def __init__(self, error: Exception | None = None) -> None:
        self.rows: list[SpeechUsage] = []
        self._error = error

    async def record(self, usage: SpeechUsage) -> None:
        if self._error:
            raise self._error
        self.rows.append(usage)


class FakeSTT:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        if self._error:
            raise self._error
        return Transcript("namaste", "hi-IN", 0.9, audio.duration_s)


class FakeTTS:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        if self._error:
            raise self._error
        return b"wav"


def test_sarvam_costs_follow_the_published_rates() -> None:
    assert stt_cost_inr("sarvam", Decimal(3600)) == Decimal("30.0000")
    assert tts_cost_inr("sarvam", 10_000) == Decimal("30.0000")


def test_an_unknown_provider_is_costed_at_zero_rather_than_guessed() -> None:
    assert stt_cost_inr("other", Decimal(60)) == Decimal(0)
    assert tts_cost_inr("other", 100) == Decimal(0)


async def test_a_transcription_is_recorded_by_audio_seconds() -> None:
    sink = Sink()
    stt = MeteredSTT(FakeSTT(), sink, provider="sarvam")

    transcript = await stt.transcribe(AUDIO, lang_hint=None)

    assert transcript.text == "namaste"
    assert [(r.provider, r.kind, r.amount) for r in sink.rows] == [
        ("sarvam", "stt", Decimal("12.5"))
    ]
    assert sink.rows[0].est_cost_inr == stt_cost_inr("sarvam", Decimal("12.5"))


async def test_a_synthesis_is_recorded_by_characters() -> None:
    sink = Sink()
    tts = MeteredTTS(FakeTTS(), sink, provider="sarvam")

    assert await tts.synthesize("नमस्ते", "hi", VOICE) == b"wav"

    assert [(r.provider, r.kind, r.amount) for r in sink.rows] == [("sarvam", "tts", Decimal(6))]


@pytest.mark.parametrize("kind", ["stt", "tts"])
async def test_a_failed_call_costs_nothing_and_still_raises(kind: str) -> None:
    sink = Sink()
    failure = SpeechProviderError("down")
    with pytest.raises(SpeechProviderError):
        if kind == "stt":
            await MeteredSTT(FakeSTT(failure), sink, provider="sarvam").transcribe(
                AUDIO, lang_hint=None
            )
        else:
            await MeteredTTS(FakeTTS(failure), sink, provider="sarvam").synthesize("x", "en", VOICE)
    assert sink.rows == []


async def test_a_broken_sink_never_costs_the_teacher_their_reply() -> None:
    sink = Sink(RuntimeError("db down"))

    transcript = await MeteredSTT(FakeSTT(), sink, provider="sarvam").transcribe(
        AUDIO, lang_hint=None
    )
    audio = await MeteredTTS(FakeTTS(), sink, provider="sarvam").synthesize("hi", "en", VOICE)

    assert transcript.text == "namaste" and audio == b"wav"
