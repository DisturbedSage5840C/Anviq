"""What the conversation brain sees and says, independent of WhatsApp and speech vendors."""

from dataclasses import dataclass, field
from typing import Protocol


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
class Reply:
    text: str
    lang: str
    speak: bool = True


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
