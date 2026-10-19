"""Shared fakes for scripted WhatsApp conversations through the real pipeline and router.

Only the network edges (WhatsApp, STT, TTS, audio transcoding) are faked, so the tests built on
this pin what a teacher actually sees and hears, in order.
"""

from dataclasses import dataclass, field

from app.channel.audio import PreparedAudio
from app.channel.messages import InboundKind, InboundMessage
from app.channel.pipeline import InboundPipeline
from app.channel.whatsapp_client import DownloadedMedia
from app.content.copy import render
from app.core.daily_loop import DailyLoop
from app.core.rehearsal_flow import Rehearsals
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


def welcome_to_menu(lang: str) -> str:
    """What the teacher reads right after agreeing to the consent notice."""
    return f"{render('consent_thanks', lang)}\n\n{render('menu', lang)}"


def transcript(text: str, code: str = "hi-IN") -> Transcript:
    return Transcript(text, code, 0.95, 3.0)


def text_message(body: str) -> InboundMessage:
    return InboundMessage("wamid.t", SENDER, InboundKind.TEXT, 1, text=body)


def voice_message() -> InboundMessage:
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


def make_harness(
    *transcripts: Transcript,
    loop: DailyLoop | None = None,
    rehearsal: Rehearsals | None = None,
) -> Harness:
    whatsapp, store = FakeWhatsApp(), InMemoryTeacherStore()
    pipeline = InboundPipeline(
        whatsapp=whatsapp,
        stt=ScriptedSTT(list(transcripts)),
        tts=FakeTTS(),
        brain=RouterBrain(store, PEPPER, loop=loop, rehearsal=rehearsal),
        voice=Voice("ritu"),
        prepare_audio=_prepare,
        encode_voice=_voice_note,
    )
    return Harness(pipeline, whatsapp, store)
