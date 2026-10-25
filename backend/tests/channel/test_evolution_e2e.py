"""Scripted WhatsApp conversations over the Evolution channel, from webhook JSON to the wire.

Only the Evolution HTTP server, STT, TTS and audio transcoding are faked. The webhook parser, the
Evolution client, the pipeline and the router are the real ones, so these tests pin what the
teacher receives and exactly what we post to Evolution.
"""

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.channel.audio import PreparedAudio
from app.channel.evolution_client import EvolutionWhatsAppClient
from app.channel.evolution_messages import parse_evolution_inbound
from app.channel.pipeline import InboundPipeline
from app.core.router_brain import RouterBrain
from app.core.teacher_store import InMemoryTeacherStore
from app.speech.base import Transcript, Voice
from tests.channel.e2e_support import (
    PEPPER,
    SENDER,
    FakeTTS,
    ScriptedSTT,
    transcript,
    welcome_to_first_practice,
)

BASE_URL = "http://evolution:8080"
INSTANCE = "anviq-demo"
API_KEY = "test-evolution-key"
NOW = 1_800_000_000
SEND_TEXT = f"/message/sendText/{INSTANCE}"
SEND_AUDIO = f"/message/sendWhatsAppAudio/{INSTANCE}"
FETCH_MEDIA = f"/chat/getBase64FromMediaMessage/{INSTANCE}"
VOICE_NOTE = b"ogg-opus"


@dataclass
class FakeEvolution:
    """Answers like Evolution and records every request it receives."""

    audio_status: int = 201
    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.path, dict(request.headers), body))
        if request.url.path == FETCH_MEDIA:
            audio = base64.b64encode(b"ogg").decode()
            return httpx.Response(201, json={"base64": audio, "mimetype": "audio/ogg"})
        status = self.audio_status if request.url.path == SEND_AUDIO else 201
        return httpx.Response(status, json={"key": {"id": "OUT1"}})

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [body for call_path, _, body in self.calls if call_path == path]


@dataclass
class Conversation:
    pipeline: InboundPipeline
    evolution: FakeEvolution
    store: InMemoryTeacherStore
    _count: int = 0

    async def receive(self, message: dict[str, Any], *, from_me: bool = False) -> None:
        self._count += 1
        payload = {
            "event": "messages.upsert",
            "instance": INSTANCE,
            "data": {
                "key": {
                    "remoteJid": f"{SENDER}@s.whatsapp.net",
                    "fromMe": from_me,
                    "id": f"3EB0{self._count:04d}",
                },
                "message": message,
                "messageTimestamp": NOW - 5,
            },
        }
        parsed = parse_evolution_inbound(payload, now=NOW)
        if parsed is not None:
            await self.pipeline.handle(parsed)

    async def type(self, body: str) -> None:
        await self.receive({"conversation": body})

    async def speak(self) -> None:
        await self.receive({"audioMessage": {"mimetype": "audio/ogg; codecs=opus", "ptt": True}})

    def texts(self) -> list[str]:
        return [body["text"] for body in self.evolution.bodies(SEND_TEXT)]


async def _prepare(audio: bytes) -> PreparedAudio:
    return PreparedAudio(b"wav", 3.0)


async def _voice_note(wav: bytes) -> bytes:
    return VOICE_NOTE


def make_conversation(*transcripts: Transcript, audio_status: int = 201) -> Conversation:
    evolution = FakeEvolution(audio_status=audio_status)
    http = httpx.AsyncClient(transport=httpx.MockTransport(evolution.handle))
    client = EvolutionWhatsAppClient(
        http, base_url=BASE_URL, api_key=API_KEY, instance=INSTANCE, retry_delay_s=0
    )
    store = InMemoryTeacherStore()
    pipeline = InboundPipeline(
        whatsapp=client,
        stt=ScriptedSTT(list(transcripts)),
        tts=FakeTTS(),
        brain=RouterBrain(store, PEPPER),
        voice=Voice("ritu"),
        prepare_audio=_prepare,
        encode_voice=_voice_note,
    )
    return Conversation(pipeline, evolution, store)


async def test_a_typed_onboarding_is_answered_in_text_and_voice_over_evolution():
    chat = make_conversation()

    for body in ("hello", "English", "2", "yes"):
        await chat.type(body)

    assert chat.texts()[-1] == welcome_to_first_practice("en")
    assert len(chat.evolution.bodies(SEND_AUDIO)) == 3


async def test_replies_go_to_the_teachers_number_with_the_api_key():
    chat = make_conversation()

    await chat.type("hello")

    path, headers, body = chat.evolution.calls[0]
    assert (path, body["number"]) == (SEND_TEXT, SENDER)
    assert headers["apikey"] == API_KEY


async def test_a_voice_reply_posts_the_audio_inline_as_a_voice_note():
    chat = make_conversation()
    for body in ("hello", "English"):
        await chat.type(body)

    audio = chat.evolution.bodies(SEND_AUDIO)[0]

    assert base64.b64decode(audio["audio"]) == VOICE_NOTE
    assert audio["encoding"] is False


async def test_a_teacher_can_onboard_entirely_by_voice_note_over_evolution():
    chat = make_conversation(
        transcript("नमस्ते"),
        transcript("हिंदी"),
        transcript("दो और तीन मिली-जुली"),
        transcript("हाँ"),
    )

    for _ in range(4):
        await chat.speak()

    assert chat.texts()[-1] == welcome_to_first_practice("hi")
    fetched = [body["message"]["key"]["id"] for body in chat.evolution.bodies(FETCH_MEDIA)]
    assert fetched == ["3EB00001", "3EB00002", "3EB00003", "3EB00004"]


async def test_the_text_reply_still_arrives_when_evolution_refuses_the_voice_note():
    chat = make_conversation(audio_status=500)

    for body in ("hello", "English", "2", "yes"):
        await chat.type(body)

    assert chat.texts()[-1] == welcome_to_first_practice("en")


async def test_our_own_echoed_message_never_triggers_a_reply():
    chat = make_conversation()

    await chat.receive({"conversation": "Welcome to Anviq"}, from_me=True)

    assert chat.evolution.calls == []


async def test_an_image_gets_the_polite_unsupported_reply_and_no_voice_note():
    chat = make_conversation()

    await chat.receive({"imageMessage": {"mimetype": "image/jpeg"}})

    assert len(chat.texts()) == 1
    assert chat.evolution.bodies(SEND_AUDIO) == []
