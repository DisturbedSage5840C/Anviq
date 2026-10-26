import asyncio
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


def test_bulbul_v4_flash_costs_a_third_of_bulbul_v3_per_character() -> None:
    assert tts_cost_inr("sarvam", 10_000, model="bulbul:v4-flash") == Decimal("10.0000")
    assert tts_cost_inr("sarvam", 10_000, model="bulbul:v3") == Decimal("30.0000")


def test_a_model_without_its_own_rate_is_costed_at_the_providers_default() -> None:
    assert tts_cost_inr("sarvam", 10_000, model="bulbul:v9") == tts_cost_inr("sarvam", 10_000)
    assert tts_cost_inr("google", 1000, model="bulbul:v4-flash") == Decimal("1.3440")


async def test_a_synthesis_is_priced_at_the_model_it_was_spoken_by() -> None:
    sink = Sink()
    tts = MeteredTTS(FakeTTS(), sink, provider="sarvam", model="bulbul:v4-flash")

    await tts.synthesize("a" * 1000, "en", VOICE)

    assert sink.rows[0].est_cost_inr == Decimal("1.0000")


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


async def test_a_broken_sink_never_costs_the_teacher_their_reply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = Sink(RuntimeError("db down"))

    transcript = await MeteredSTT(FakeSTT(), sink, provider="sarvam").transcribe(
        AUDIO, lang_hint=None
    )
    audio = await MeteredTTS(FakeTTS(), sink, provider="sarvam").synthesize("hi", "en", VOICE)

    assert transcript.text == "namaste" and audio == b"wav"
    assert caplog.text.count("could not record speech usage") == 2


async def test_a_sink_that_hangs_is_cut_off_and_the_reply_still_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.speech.metering.SINK_TIMEOUT_S", 0.01)

    class HangingSink:
        async def record(self, usage: SpeechUsage) -> None:
            await asyncio.sleep(10)

    audio = await MeteredTTS(FakeTTS(), HangingSink(), provider="sarvam").synthesize(
        "hi", "en", VOICE
    )

    assert audio == b"wav"


def test_google_costs_use_their_own_rates_and_round_to_four_places() -> None:
    assert stt_cost_inr("google", Decimal(60)) == Decimal("1.3440")
    assert tts_cost_inr("google", 1000) == Decimal("1.3440")
    assert stt_cost_inr("sarvam", Decimal("0.3")) == Decimal("0.0025")
