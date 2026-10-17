import io
import math
import struct
import wave

import pytest

from app.channel import audio
from app.channel.audio import (
    AudioDecodeError,
    AudioTooLargeError,
    AudioTooLongError,
    prepare_for_stt,
    to_voice_note,
)


def make_wav(seconds: float, rate: int = 16000, tone_hz: float = 440.0) -> bytes:
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * tone_hz * n / rate)))
        for n in range(int(seconds * rate))
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(frames)
    return buffer.getvalue()


async def test_voice_note_is_ogg_opus_mono_under_whatsapp_inline_limit() -> None:
    ogg = await to_voice_note(make_wav(2.0, rate=24000))

    assert ogg.startswith(b"OggS")
    head = ogg.index(b"OpusHead")
    channels = ogg[head + 9]
    assert channels == 1
    assert len(ogg) <= audio.MAX_VOICE_NOTE_BYTES


async def test_prepare_for_stt_returns_16k_mono_wav_with_duration() -> None:
    prepared = await prepare_for_stt(make_wav(1.5, rate=8000))

    with wave.open(io.BytesIO(prepared.wav), "rb") as reader:
        assert reader.getframerate() == 16000
        assert reader.getnchannels() == 1
    assert prepared.duration_s == pytest.approx(1.5, abs=0.05)


async def test_prepare_for_stt_rejects_clips_over_the_two_minute_limit() -> None:
    long_clip = make_wav(audio.MAX_VOICE_SECONDS + 1, rate=8000)

    with pytest.raises(AudioTooLongError):
        await prepare_for_stt(long_clip)


async def test_undecodable_bytes_raise_a_decode_error() -> None:
    with pytest.raises(AudioDecodeError):
        await prepare_for_stt(b"this is not audio")


async def test_voice_note_that_cannot_fit_the_limit_raises(monkeypatch) -> None:
    monkeypatch.setattr(audio, "MAX_VOICE_NOTE_BYTES", 500)

    with pytest.raises(AudioTooLargeError):
        await to_voice_note(make_wav(2.0, rate=24000))
