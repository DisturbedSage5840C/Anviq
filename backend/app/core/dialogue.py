"""What the conversation brain sees and says, independent of WhatsApp and speech vendors."""

from dataclasses import dataclass, field
from typing import Protocol

from app.speech.prepare import to_spoken


@dataclass(frozen=True)
class Utterance:
    sender_wa_id: str
    text: str
    lang: str
    via_voice: bool
    needs_confirmation: bool
    # The teacher's own recording, kept off repr and equality so it never reaches a log line.
    audio: bytes | None = field(default=None, repr=False, compare=False)
    audio_mime: str = field(default="audio/ogg", repr=False, compare=False)


@dataclass(frozen=True)
class ClipAudio:
    """A recording the teacher chose to keep, played back to them under a short label."""

    # Kept off repr and equality so the recording never reaches a log line.
    audio: bytes = field(repr=False, compare=False)
    mime: str
    label: str


@dataclass(frozen=True)
class Reply:
    text: str
    lang: str
    speak: bool = True
    clips: tuple[ClipAudio, ...] = ()
    # What the voice note says when it should differ from `text`; None means "say the text,
    # cleaned for the ear" (see app.speech.prepare).
    spoken: str | None = None

    def voice_text(self) -> str:
        """The words for text-to-speech: the reply's own spoken form, else its text cleaned.

        Empty when nothing is left to say aloud (a reply that was only a symbol).
        """
        if self.spoken is not None:
            return self.spoken
        return to_spoken(self.text, self.lang)


class Brain(Protocol):
    async def respond(self, utterance: Utterance) -> Reply: ...


_CONFIRM_BACK = {
    "hi": "मैंने सुना: '{text}' — सही है?",
    "en": "I heard: '{text}'. Is that right?",
}


class EchoBrain:
    """Repeats the teacher back. Proves the voice loop end to end before the router exists."""

    async def respond(self, utterance: Utterance) -> Reply:
        if utterance.needs_confirmation:
            text = _CONFIRM_BACK[utterance.lang].format(text=utterance.text)
            return Reply(text, utterance.lang)
        return Reply(utterance.text, utterance.lang)
