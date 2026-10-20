"""One web-room turn: text or a recording in, the brain's reply plus a spoken copy out.

The same STT, brain and TTS as the WhatsApp pipeline, minus the WhatsApp delivery: the reply
goes back in the HTTP response. Nothing here knows who the visitor is beyond an opaque id.
"""

import logging
from dataclasses import dataclass

from app.ai import build_router_brain
from app.channel import replies
from app.channel.audio import prepare_for_stt
from app.channel.pipeline import PrepareAudio, spoken_utterance, transcribe_audio
from app.config import Settings
from app.core.dialogue import Brain, Reply, Utterance
from app.resources import Resources
from app.speech.base import SpeechProviderError, STTProvider, TTSProvider, Voice
from app.speech.voices import COACH_PERSONA, voice_for

logger = logging.getLogger(__name__)

DEFAULT_LANG = "hi"


@dataclass(frozen=True)
class WebReply:
    text: str
    lang: str
    audio_wav: bytes | None
    # The coach could not help (unclear audio, voice off).
    refused: bool = False
    # Nothing paid for ran, so the turn is given back. A refusal after decoding and speech-to-text
    # keeps its cost, otherwise unusable audio would be a free way to burn that work.
    free: bool = False


class WebTurn:
    def __init__(
        self,
        *,
        stt: STTProvider | None,
        tts: TTSProvider | None,
        brain: Brain,
        voice: Voice,
        prepare_audio: PrepareAudio = prepare_for_stt,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._brain = brain
        self._voice = voice
        self._prepare_audio = prepare_audio

    async def respond_to_text(self, sender: str, text: str) -> WebReply:
        return await self._answer(
            Utterance(sender, text, DEFAULT_LANG, via_voice=False, needs_confirmation=False)
        )

    async def respond_to_audio(self, sender: str, audio: bytes) -> WebReply:
        if self._stt is None:
            return _refusal(replies.VOICE_UNAVAILABLE, free=True)
        transcript = await transcribe_audio(self._stt, self._prepare_audio, audio)
        if isinstance(transcript, str):
            return _refusal(transcript)
        return await self._answer(spoken_utterance(sender, transcript))

    async def _answer(self, utterance: Utterance) -> WebReply:
        reply = await self._brain.respond(utterance)
        return WebReply(reply.text, reply.lang, await self._speak(reply))

    async def _speak(self, reply: Reply) -> bytes | None:
        if not reply.speak or self._tts is None:
            return None
        try:
            return await self._tts.synthesize(reply.text, reply.lang, self._voice)
        except SpeechProviderError:
            logger.warning("voice reply failed; text only", exc_info=True)
            return None


def _refusal(text: str, *, free: bool = False) -> WebReply:
    return WebReply(text, DEFAULT_LANG, None, refused=True, free=free)


def build_web_turn(resources: Resources, settings: Settings) -> WebTurn:
    return WebTurn(
        stt=resources.stt,
        tts=resources.tts,
        brain=build_router_brain(resources, settings),
        voice=voice_for(settings.tts_provider, COACH_PERSONA),
    )
