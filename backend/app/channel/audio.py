"""ffmpeg transcoding for WhatsApp voice notes.

Audio only ever moves through ffmpeg's stdin/stdout, so raw teacher audio is
never written to disk.
"""

import asyncio
import io
import wave
from dataclasses import dataclass

MAX_VOICE_SECONDS = 120
# WhatsApp only shows the inline play button for voice notes up to 512 KB.
MAX_VOICE_NOTE_BYTES = 512 * 1024
VOICE_BITRATE_LADDER_KBPS = (24, 16, 12)
STT_SAMPLE_RATE = 16000
PCM_BYTES_PER_SAMPLE = 2
FFMPEG_TIMEOUT_S = 30.0


class AudioError(Exception):
    """Base class for audio pipeline failures."""


class AudioDecodeError(AudioError):
    """ffmpeg could not read the input as audio."""


class AudioTooLongError(AudioError):
    """Voice note is longer than the allowed limit."""


class AudioTooLargeError(AudioError):
    """Encoded voice note cannot fit WhatsApp's inline-play size limit."""


@dataclass(frozen=True)
class PreparedAudio:
    wav: bytes
    duration_s: float


async def _ffmpeg(data: bytes, *output_args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(  # noqa: S603 - constant argv, data via stdin
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        *output_args,
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(data), FFMPEG_TIMEOUT_S)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise AudioDecodeError("ffmpeg timed out") from None
    if process.returncode != 0 or not stdout:
        raise AudioDecodeError("ffmpeg could not decode the audio")
    return stdout


async def to_voice_note(wav: bytes) -> bytes:
    """Encode to mono OGG/Opus, lowering the bitrate until it fits the inline limit."""
    for bitrate in VOICE_BITRATE_LADDER_KBPS:
        ogg = await _ffmpeg(
            wav, "-ac", "1", "-c:a", "libopus", "-b:a", f"{bitrate}k", "-application", "voip",
            "-f", "ogg",
        )  # fmt: skip
        if len(ogg) <= MAX_VOICE_NOTE_BYTES:
            return ogg
    raise AudioTooLargeError("Voice note does not fit WhatsApp's 512 KB inline limit")


async def prepare_for_stt(audio: bytes) -> PreparedAudio:
    """Decode anything ffmpeg understands to 16 kHz mono WAV and enforce the length limit."""
    pcm = await _ffmpeg(
        audio, "-ac", "1", "-ar", str(STT_SAMPLE_RATE), "-f", "s16le"
    )  # fmt: skip
    duration_s = len(pcm) / (STT_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
    if duration_s > MAX_VOICE_SECONDS:
        raise AudioTooLongError(f"Voice note is longer than {MAX_VOICE_SECONDS} seconds")
    return PreparedAudio(wav=_wrap_wav(pcm), duration_s=duration_s)


def _wrap_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(PCM_BYTES_PER_SAMPLE)
        writer.setframerate(STT_SAMPLE_RATE)
        writer.writeframes(pcm)
    return buffer.getvalue()
