"""One inbound WhatsApp message to one reply: transcribe, ask the brain, answer in text + voice.

Expected failures (bad audio, vendor outage, unsupported media) become a polite reply to the
teacher; anything else propagates so the job queue can retry. The written reply is always
sent before the voice note, so a TTS or upload failure never loses the answer.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.channel import replies
from app.channel.audio import (
    AudioDecodeError,
    AudioTooLongError,
    PreparedAudio,
    prepare_for_stt,
    to_voice_note,
)
from app.channel.messages import InboundKind, InboundMessage
from app.channel.whatsapp_client import (
    OGG_OPUS_MIME,
    DownloadedMedia,
    MediaTooLargeError,
    WhatsAppError,
)
from app.core.dialogue import Brain, Reply, Utterance
from app.speech.base import SpeechProviderError, STTProvider, Transcript, TTSProvider, Voice
from app.speech.confirm import needs_confirmation

logger = logging.getLogger(__name__)

PrepareAudio = Callable[[bytes], Awaitable[PreparedAudio]]
EncodeVoice = Callable[[bytes], Awaitable[bytes]]


class WhatsAppPort(Protocol):
    async def send_text(self, to: str, body: str) -> str: ...
    async def send_audio(self, to: str, media_id: str) -> str: ...
    async def upload_media(self, data: bytes, mime_type: str) -> str: ...
    async def download_media(self, media_id: str) -> DownloadedMedia: ...


def language_of(language_code: str) -> str:
    return "en" if language_code.lower().startswith("en") else "hi"


async def transcribe_audio(
    stt: STTProvider, prepare_audio: PrepareAudio, data: bytes
) -> Transcript | str:
    """The words in a recording, or the polite refusal to send instead. Shared with the web room."""
    try:
        transcript = await stt.transcribe(await prepare_audio(data), lang_hint=None)
    except AudioTooLongError:
        return replies.AUDIO_TOO_LONG
    except (AudioDecodeError, SpeechProviderError):
        logger.warning("could not transcribe voice note", exc_info=True)
        return replies.CANNOT_HEAR
    return transcript if transcript.text.strip() else replies.CANNOT_HEAR


def spoken_utterance(
    sender: str, transcript: Transcript, audio: bytes | None = None, audio_mime: str = OGG_OPUS_MIME
) -> Utterance:
    """`audio` is the teacher's recording, carried only so the brain can keep it if they asked."""
    return Utterance(
        sender,
        transcript.text,
        language_of(transcript.language_code),
        via_voice=True,
        needs_confirmation=needs_confirmation(transcript),
        audio=audio,
        audio_mime=audio_mime,
    )


class InboundPipeline:
    def __init__(
        self,
        *,
        whatsapp: WhatsAppPort,
        stt: STTProvider | None,
        tts: TTSProvider | None,
        brain: Brain,
        voice: Voice,
        prepare_audio: PrepareAudio = prepare_for_stt,
        encode_voice: EncodeVoice = to_voice_note,
    ) -> None:
        self._whatsapp = whatsapp
        self._stt = stt
        self._tts = tts
        self._brain = brain
        self._voice = voice
        self._prepare_audio = prepare_audio
        self._encode_voice = encode_voice

    async def handle(self, message: InboundMessage) -> None:
        sender = message.sender_wa_id
        if message.kind is InboundKind.UNSUPPORTED:
            await self._whatsapp.send_text(sender, replies.UNSUPPORTED)
            return
        utterance = await self._to_utterance(message)
        if isinstance(utterance, str):
            await self._whatsapp.send_text(sender, utterance)
            return
        await self._deliver(sender, await self._brain.respond(utterance))

    async def _to_utterance(self, message: InboundMessage) -> Utterance | str:
        """The teacher's words, or the polite refusal text to send instead."""
        if message.kind is not InboundKind.AUDIO:
            text = message.text or message.button_id or ""
            return Utterance(message.sender_wa_id, text, "hi", False, False)
        if self._stt is None:
            return replies.VOICE_UNAVAILABLE
        try:
            media = await self._whatsapp.download_media(message.media_id or "")
        except MediaTooLargeError:
            return replies.MEDIA_TOO_LARGE
        transcript = await transcribe_audio(self._stt, self._prepare_audio, media.data)
        if isinstance(transcript, str):
            return transcript
        return spoken_utterance(message.sender_wa_id, transcript, media.data, media.mime_type)

    async def _deliver(self, sender: str, reply: Reply) -> None:
        await self._whatsapp.send_text(sender, reply.text)
        await self._deliver_voice(sender, reply)
        await self._deliver_clips(sender, reply)

    async def _deliver_clips(self, sender: str, reply: Reply) -> None:
        """The teacher's own kept recordings, each under a label. The text is already delivered."""
        for clip in reply.clips:
            try:
                await self._whatsapp.send_text(sender, clip.label)
                media_id = await self._whatsapp.upload_media(clip.audio, clip.mime)
                await self._whatsapp.send_audio(sender, media_id)
            except WhatsAppError:
                logger.warning("mirror clip not sent; text was delivered", exc_info=True)
                return

    async def _deliver_voice(self, sender: str, reply: Reply) -> None:
        if not reply.speak or self._tts is None:
            return
        try:
            wav = await self._tts.synthesize(reply.text, reply.lang, self._voice)
            media_id = await self._whatsapp.upload_media(
                await self._encode_voice(wav), OGG_OPUS_MIME
            )
            await self._whatsapp.send_audio(sender, media_id)
        except (SpeechProviderError, WhatsAppError):
            logger.warning("voice reply failed; text was delivered", exc_info=True)
