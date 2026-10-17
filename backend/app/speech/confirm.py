"""Decides when to read a transcript back to the teacher before acting on it."""

import re

from app.speech.base import Transcript

MIN_CONFIDENCE = 0.6
MIN_TRANSCRIPT_CHARS = 3
_PUNCTUATION = re.compile(r"[\s.,!?।|]+")
# Short answers that are legitimately tiny: consent, deletion and yes/no prompts.
_KNOWN_SHORT_ANSWERS = frozenset(
    {"हाँ", "हां", "नहीं", "नही", "yes", "no", "ok", "हाँ मिटाओ", "हां मिटाओ", "ठीक है"}
)


def _normalise(text: str) -> str:
    return _PUNCTUATION.sub(" ", text).strip().casefold()


def needs_confirmation(transcript: Transcript) -> bool:
    """True when we should reply "I heard: '…' — is that right?" instead of acting."""
    normalised = _normalise(transcript.text)
    if normalised in _KNOWN_SHORT_ANSWERS:
        return False
    if len(normalised) < MIN_TRANSCRIPT_CHARS:
        return True
    # Providers that return no score are trusted; otherwise every turn would be a confirm-back.
    return transcript.confidence is not None and transcript.confidence < MIN_CONFIDENCE
