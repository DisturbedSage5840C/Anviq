"""One web turn: text or a recording in, the brain's reply (and a spoken copy) out."""

import pytest

from app.channel import replies
from app.channel.audio import AudioDecodeError, AudioTooLongError, PreparedAudio
from app.core.dialogue import Reply, Utterance
from app.speech.base import SpeechProviderError, Transcript, Voice
from app.web.turn import WebTurn

SENDER = "web:abc"
WAV = b"RIFF-fake-wav"


class _Brain:
    def __init__(self, reply: Reply | None = None) -> None:
        self.reply = reply or Reply("नमस्ते", "hi")
        self.heard: list[Utterance] = []

    async def respond(self, utterance: Utterance) -> Reply:
        self.heard.append(utterance)
        return self.reply


class _STT:
    def __init__(self, transcript: Transcript | Exception) -> None:
        self._transcript = transcript

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        if isinstance(self._transcript, Exception):
            raise self._transcript
        return self._transcript


class _TTS:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.spoken: list[tuple[str, str]] = []

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        if self._error:
            raise self._error
        self.spoken.append((text, lang))
        return WAV


async def _prepare(audio: bytes) -> PreparedAudio:
    return PreparedAudio(wav=audio, duration_s=3.0)


def _transcript(text: str = "कल का प्लान", code: str = "hi-IN") -> Transcript:
    return Transcript(text=text, language_code=code, confidence=0.95, duration_s=3.0)


def _turn(brain=None, stt=None, tts=None, prepare=_prepare) -> WebTurn:
    return WebTurn(
        stt=stt,
        tts=tts,
        brain=brain or _Brain(),
        voice=Voice("ritu"),
        prepare_audio=prepare,
    )


async def test_a_typed_turn_reaches_the_brain_as_text_and_comes_back_spoken():
    brain, tts = _Brain(), _TTS()

    reply = await _turn(brain, tts=tts).respond_to_text(SENDER, "plan")

    assert brain.heard == [Utterance(SENDER, "plan", "hi", False, False)]
    assert (reply.text, reply.lang, reply.audio_wav) == ("नमस्ते", "hi", WAV)
    assert tts.spoken == [("नमस्ते", "hi")]


async def test_a_recording_is_transcribed_before_it_reaches_the_brain():
    brain = _Brain()
    stt = _STT(_transcript("what is the plan", "en-IN"))

    await _turn(brain, stt=stt).respond_to_audio(SENDER, b"webm-bytes")

    heard = brain.heard[0]
    assert (heard.text, heard.lang, heard.via_voice) == ("what is the plan", "en", True)


@pytest.mark.parametrize(
    ("failure", "refusal"),
    [
        (AudioTooLongError("long"), replies.AUDIO_TOO_LONG),
        (AudioDecodeError("garbled"), replies.CANNOT_HEAR),
    ],
)
async def test_unusable_audio_gets_a_polite_refusal_and_never_reaches_the_brain(
    failure: Exception, refusal: str
):
    async def prepare(audio: bytes) -> PreparedAudio:
        raise failure

    brain = _Brain()

    reply = await _turn(brain, stt=_STT(_transcript()), prepare=prepare).respond_to_audio(
        SENDER, b"x"
    )

    assert (reply.text, reply.audio_wav, brain.heard) == (refusal, None, [])


async def test_a_vendor_failure_or_silence_reads_as_cannot_hear():
    failing = _turn(stt=_STT(SpeechProviderError("down")))
    silent = _turn(stt=_STT(_transcript("   ")))

    replies_ = [
        await failing.respond_to_audio(SENDER, b"x"),
        await silent.respond_to_audio(SENDER, b"x"),
    ]

    assert [reply.text for reply in replies_] == [replies.CANNOT_HEAR] * 2


async def test_without_a_speech_to_text_provider_recordings_are_declined():
    reply = await _turn(stt=None).respond_to_audio(SENDER, b"x")

    assert reply.text == replies.VOICE_UNAVAILABLE


async def test_a_text_reply_survives_a_text_to_speech_failure():
    tts = _TTS(SpeechProviderError("down"))

    reply = await _turn(tts=tts).respond_to_text(SENDER, "plan")

    assert (reply.text, reply.audio_wav) == ("नमस्ते", None)


async def test_no_voice_is_made_when_the_brain_says_not_to_speak_or_tts_is_off():
    quiet = _turn(_Brain(Reply("ok", "en", speak=False)), tts=_TTS())
    mute = _turn(tts=None)

    assert (await quiet.respond_to_text(SENDER, "x")).audio_wav is None
    assert (await mute.respond_to_text(SENDER, "x")).audio_wav is None


async def test_refusals_are_marked_so_the_turn_can_be_given_back():
    unavailable = await _turn(stt=None).respond_to_audio(SENDER, b"audio")
    unclear = await _turn(stt=_STT(_transcript(text="  "))).respond_to_audio(SENDER, b"audio")

    assert (unavailable.refused, unclear.refused) == (True, True)


async def test_a_coach_reply_is_not_marked_refused():
    spoken = await _turn(stt=_STT(_transcript())).respond_to_audio(SENDER, b"audio")
    typed = await _turn().respond_to_text(SENDER, "कल का प्लान")

    assert (spoken.refused, typed.refused) == (False, False)
