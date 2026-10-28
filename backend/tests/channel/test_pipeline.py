from dataclasses import dataclass, field
from typing import Any

import pytest

from app.channel.audio import AudioDecodeError, AudioTooLongError, PreparedAudio
from app.channel.messages import InboundKind, InboundMessage
from app.channel.pipeline import InboundPipeline
from app.channel.replies import (
    AUDIO_TOO_LONG,
    CANNOT_HEAR,
    MEDIA_TOO_LARGE,
    UNSUPPORTED,
    VOICE_UNAVAILABLE,
)
from app.channel.whatsapp_client import DownloadedMedia, MediaTooLargeError, WhatsAppError
from app.core.dialogue import ClipAudio, Reply, Utterance
from app.speech.base import SpeechProviderError, Transcript, Voice

SENDER = "919999900000"
VOICE = Voice("ritu")


@dataclass
class FakeWhatsApp:
    sent: list[tuple[str, str]] = field(default_factory=list)
    media: DownloadedMedia | Exception = DownloadedMedia(b"ogg", "audio/ogg")
    upload_error: Exception | None = None
    uploads: list[tuple[bytes, str]] = field(default_factory=list)

    async def send_text(self, to: str, body: str) -> str:
        self.sent.append(("text", body))
        return "wamid.out"

    async def send_audio(self, to: str, media_id: str) -> str:
        self.sent.append(("audio", media_id))
        return "wamid.out"

    async def upload_media(self, data: bytes, mime_type: str) -> str:
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((data, mime_type))
        return "media-1"

    async def download_media(self, media_id: str) -> DownloadedMedia:
        if isinstance(self.media, Exception):
            raise self.media
        return self.media


@dataclass
class FakeSTT:
    transcript: Transcript | Exception = Transcript("दो जमा दो", "hi-IN", 0.95, 3.0)

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        if isinstance(self.transcript, Exception):
            raise self.transcript
        return self.transcript


@dataclass
class FakeTTS:
    error: Exception | None = None

    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        if self.error is not None:
            raise self.error
        return b"wav"


@dataclass
class RecordingBrain:
    reply: Reply = Reply("ठीक है", "hi")
    seen: list[Utterance] = field(default_factory=list)

    async def respond(self, utterance: Utterance) -> Reply:
        self.seen.append(utterance)
        return self.reply


async def _prepare(audio: bytes) -> PreparedAudio:
    return PreparedAudio(b"wav", 3.0)


async def _voice_note(wav: bytes) -> bytes:
    return b"ogg-opus"


def _pipeline(
    whatsapp: FakeWhatsApp,
    brain: RecordingBrain,
    *,
    stt: Any = None,
    tts: Any = None,
    prepare: Any = _prepare,
) -> InboundPipeline:
    return InboundPipeline(
        whatsapp=whatsapp,
        stt=stt,
        tts=tts,
        brain=brain,
        voice=VOICE,
        prepare_audio=prepare,
        encode_voice=_voice_note,
    )


def _text(body: str = "नमस्ते") -> InboundMessage:
    return InboundMessage("wamid.1", SENDER, InboundKind.TEXT, 1, text=body)


def _audio() -> InboundMessage:
    return InboundMessage(
        "wamid.2", SENDER, InboundKind.AUDIO, 1, media_id="m1", mime_type="audio/ogg"
    )


async def test_text_message_gets_a_written_and_spoken_reply():
    whatsapp, brain = FakeWhatsApp(), RecordingBrain()

    await _pipeline(whatsapp, brain, tts=FakeTTS()).handle(_text())

    assert brain.seen == [
        Utterance(SENDER, "नमस्ते", "hi", via_voice=False, needs_confirmation=False)
    ]
    assert whatsapp.sent == [("text", "ठीक है"), ("audio", "media-1")]


async def test_voice_note_is_transcribed_before_reaching_the_brain():
    whatsapp, brain = FakeWhatsApp(), RecordingBrain()

    await _pipeline(whatsapp, brain, stt=FakeSTT(), tts=FakeTTS()).handle(_audio())

    (utterance,) = brain.seen
    assert (utterance.text, utterance.lang, utterance.via_voice) == ("दो जमा दो", "hi", True)
    assert utterance.needs_confirmation is False


async def test_english_transcript_is_marked_english():
    stt = FakeSTT(Transcript("two plus two", "en-IN", 0.9, 3.0))
    brain = RecordingBrain()

    await _pipeline(FakeWhatsApp(), brain, stt=stt).handle(_audio())

    assert brain.seen[0].lang == "en"


async def test_low_confidence_transcript_is_flagged_for_confirmation():
    stt = FakeSTT(Transcript("दो जमा दो", "hi-IN", 0.3, 3.0))
    brain = RecordingBrain()

    await _pipeline(FakeWhatsApp(), brain, stt=stt).handle(_audio())

    assert brain.seen[0].needs_confirmation is True


async def test_empty_transcript_asks_the_teacher_to_repeat():
    stt = FakeSTT(Transcript("", "hi-IN", 0.0, 3.0))
    whatsapp, brain = FakeWhatsApp(), RecordingBrain()

    await _pipeline(whatsapp, brain, stt=stt).handle(_audio())

    assert brain.seen == []
    assert whatsapp.sent == [("text", CANNOT_HEAR)]


async def test_button_reply_reaches_the_brain_as_its_id():
    message = InboundMessage("wamid.3", SENDER, InboundKind.BUTTON, 1, button_id="consent_yes")
    brain = RecordingBrain()

    await _pipeline(FakeWhatsApp(), brain).handle(message)

    assert brain.seen[0].text == "consent_yes"


async def test_unsupported_media_gets_a_polite_text_and_no_brain_call():
    message = InboundMessage("wamid.4", SENDER, InboundKind.UNSUPPORTED, 1)
    whatsapp, brain = FakeWhatsApp(), RecordingBrain()

    await _pipeline(whatsapp, brain).handle(message)

    assert whatsapp.sent == [("text", UNSUPPORTED)]
    assert brain.seen == []


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (AudioTooLongError("long"), AUDIO_TOO_LONG),
        (AudioDecodeError("bad"), CANNOT_HEAR),
        (SpeechProviderError("down"), CANNOT_HEAR),
    ],
)
async def test_voice_note_failures_get_a_polite_text(failure: Exception, expected: str):
    async def failing_prepare(audio: bytes) -> PreparedAudio:
        raise failure

    whatsapp, brain = FakeWhatsApp(), RecordingBrain()
    stt = FakeSTT(failure) if isinstance(failure, SpeechProviderError) else FakeSTT()

    await _pipeline(whatsapp, brain, stt=stt, prepare=failing_prepare).handle(_audio())

    assert whatsapp.sent == [("text", expected)]
    assert brain.seen == []


async def test_speech_provider_failure_is_reported_politely():
    whatsapp, brain = FakeWhatsApp(), RecordingBrain()

    await _pipeline(whatsapp, brain, stt=FakeSTT(SpeechProviderError("503"))).handle(_audio())

    assert whatsapp.sent == [("text", CANNOT_HEAR)]


async def test_oversized_media_gets_a_polite_text():
    whatsapp = FakeWhatsApp(media=MediaTooLargeError("big"))

    await _pipeline(whatsapp, RecordingBrain(), stt=FakeSTT()).handle(_audio())

    assert whatsapp.sent == [("text", MEDIA_TOO_LARGE)]


async def test_voice_note_without_a_configured_stt_asks_for_text():
    whatsapp, brain = FakeWhatsApp(), RecordingBrain()

    await _pipeline(whatsapp, brain, stt=None).handle(_audio())

    assert whatsapp.sent == [("text", VOICE_UNAVAILABLE)]
    assert brain.seen == []


async def test_tts_failure_still_delivers_the_written_reply():
    whatsapp = FakeWhatsApp()

    await _pipeline(whatsapp, RecordingBrain(), tts=FakeTTS(SpeechProviderError("x"))).handle(
        _text()
    )

    assert whatsapp.sent == [("text", "ठीक है")]


async def test_reply_without_tts_is_text_only():
    whatsapp = FakeWhatsApp()

    await _pipeline(whatsapp, RecordingBrain(), tts=None).handle(_text())

    assert whatsapp.sent == [("text", "ठीक है")]


async def test_reply_marked_text_only_is_not_spoken():
    whatsapp = FakeWhatsApp()
    brain = RecordingBrain(reply=Reply("ठीक है", "hi", speak=False))

    await _pipeline(whatsapp, brain, tts=FakeTTS()).handle(_text())

    assert whatsapp.sent == [("text", "ठीक है")]


CLIP_FIRST = ClipAudio(b"first-ogg", "audio/ogg", "First day")
CLIP_LATEST = ClipAudio(b"latest-ogg", "audio/ogg", "Today")


async def test_mirror_clips_follow_the_text_each_under_its_label():
    whatsapp = FakeWhatsApp()
    brain = RecordingBrain(Reply("THE MIRROR", "en", speak=False, clips=(CLIP_FIRST, CLIP_LATEST)))

    await _pipeline(whatsapp, brain).handle(_text())

    assert whatsapp.sent == [
        ("text", "THE MIRROR"),
        ("text", "First day"),
        ("audio", "media-1"),
        ("text", "Today"),
        ("audio", "media-1"),
    ]
    assert whatsapp.uploads == [(b"first-ogg", "audio/ogg"), (b"latest-ogg", "audio/ogg")]


async def test_mirror_clips_are_sent_after_the_spoken_reply():
    whatsapp = FakeWhatsApp()
    brain = RecordingBrain(Reply("THE MIRROR", "en", clips=(CLIP_FIRST,)))

    await _pipeline(whatsapp, brain, tts=FakeTTS()).handle(_text())

    assert [kind for kind, _ in whatsapp.sent] == ["text", "audio", "text", "audio"]
    assert whatsapp.uploads[-1] == (b"first-ogg", "audio/ogg")


async def test_a_clip_that_cannot_be_sent_does_not_lose_the_text():
    whatsapp = FakeWhatsApp(upload_error=WhatsAppError("upload failed"))
    brain = RecordingBrain(Reply("THE MIRROR", "en", speak=False, clips=(CLIP_FIRST,)))

    await _pipeline(whatsapp, brain).handle(_text())

    assert ("text", "THE MIRROR") in whatsapp.sent
    assert ("audio", "media-1") not in whatsapp.sent
