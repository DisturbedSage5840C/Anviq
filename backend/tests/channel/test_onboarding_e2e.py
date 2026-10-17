"""A scripted WhatsApp conversation through the real pipeline and the real router.

Only the network edges (WhatsApp, STT, TTS, audio transcoding) are faked, so these tests pin
what a teacher actually sees and hears, in order.
"""

from dataclasses import dataclass, field

from app.channel.audio import PreparedAudio
from app.channel.messages import InboundKind, InboundMessage
from app.channel.pipeline import InboundPipeline
from app.channel.whatsapp_client import DownloadedMedia
from app.content.copy import render
from app.core.router_brain import RouterBrain
from app.core.teacher_store import InMemoryTeacherStore
from app.speech.base import Transcript, Voice

SENDER = "919876543210"
PEPPER = bytes(range(32))


@dataclass
class FakeWhatsApp:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def send_text(self, to: str, body: str) -> str:
        self.sent.append(("text", body))
        return "wamid.out"

    async def send_audio(self, to: str, media_id: str) -> str:
        self.sent.append(("audio", media_id))
        return "wamid.out"

    async def upload_media(self, data: bytes, mime_type: str) -> str:
        return "media-1"

    async def download_media(self, media_id: str) -> DownloadedMedia:
        return DownloadedMedia(b"ogg", "audio/ogg")


@dataclass
class ScriptedSTT:
    """Returns the next scripted transcript for each voice note."""

    transcripts: list[Transcript]

    async def transcribe(self, audio: PreparedAudio, *, lang_hint: str | None) -> Transcript:
        return self.transcripts.pop(0)


class FakeTTS:
    async def synthesize(self, text: str, lang: str, voice: Voice) -> bytes:
        return b"wav"


async def _prepare(audio: bytes) -> PreparedAudio:
    return PreparedAudio(b"wav", 3.0)


async def _voice_note(wav: bytes) -> bytes:
    return b"ogg-opus"


def _welcome_to_menu(lang: str) -> str:
    """What the teacher reads right after agreeing to the consent notice."""
    return f"{render('consent_thanks', lang)}\n\n{render('menu', lang)}"


def _transcript(text: str, code: str = "hi-IN") -> Transcript:
    return Transcript(text, code, 0.95, 3.0)


def _text(body: str) -> InboundMessage:
    return InboundMessage("wamid.t", SENDER, InboundKind.TEXT, 1, text=body)


def _voice() -> InboundMessage:
    return InboundMessage(
        "wamid.v", SENDER, InboundKind.AUDIO, 1, media_id="m1", mime_type="audio/ogg"
    )


@dataclass
class Harness:
    pipeline: InboundPipeline
    whatsapp: FakeWhatsApp
    store: InMemoryTeacherStore

    def texts(self) -> list[str]:
        return [body for kind, body in self.whatsapp.sent if kind == "text"]

    def audio_count(self) -> int:
        return sum(1 for kind, _ in self.whatsapp.sent if kind == "audio")


def _harness(*transcripts: Transcript) -> Harness:
    whatsapp, store = FakeWhatsApp(), InMemoryTeacherStore()
    pipeline = InboundPipeline(
        whatsapp=whatsapp,
        stt=ScriptedSTT(list(transcripts)),
        tts=FakeTTS(),
        brain=RouterBrain(store, PEPPER),
        voice=Voice("ritu"),
        prepare_audio=_prepare,
        encode_voice=_voice_note,
    )
    return Harness(pipeline, whatsapp, store)


async def test_a_teacher_can_onboard_entirely_by_voice_note():
    harness = _harness(
        _transcript("नमस्ते"),
        _transcript("हिंदी"),
        _transcript("दो और तीन मिली-जुली"),
        _transcript("हाँ"),
    )

    for _ in range(4):
        await harness.pipeline.handle(_voice())

    assert harness.texts()[-1] == _welcome_to_menu("hi")
    assert harness.audio_count() == 3  # nothing is spoken until the language is chosen


async def test_a_typed_english_onboarding_is_answered_in_text_and_voice():
    harness = _harness()

    for body in ("hello", "English", "2", "yes"):
        await harness.pipeline.handle(_text(body))

    assert harness.texts()[-1] == _welcome_to_menu("en")
    assert harness.audio_count() == 3


async def test_deleting_by_voice_erases_the_teacher_and_says_goodbye_in_their_language():
    harness = _harness(_transcript("delete my data", "en-IN"), _transcript("yes, delete", "en-IN"))
    for body in ("hello", "English", "2", "yes"):
        await harness.pipeline.handle(_text(body))

    await harness.pipeline.handle(_voice())
    await harness.pipeline.handle(_voice())

    assert harness.texts()[-1] == render("deleted", "en")
    assert harness.store.teachers == {}
