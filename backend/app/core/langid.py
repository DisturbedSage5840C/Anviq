"""Which language and script a teacher typed in: a pure, deterministic guess used to understand.

Plan section 4.1 (revised 1 Nov): the session language (`TeacherState.lang`) alone decides the
language of every reply. Nothing in this module is read by the router for that; a detection is a
frozen value that callers may use to *understand* a message (which question words to look for,
what to tell the model about the teacher's wording) and never to switch language. An explicit
request such as "Hindi please" is parsed by `intents.parse_language` instead.

Script comes from the letters. Language within a script comes from small word lists; where the
evidence is thin the answer is "und" (undetermined), never a guess. Limits worth knowing:
Devanagari also writes Nepali, Konkani and Sanskrit, and the Bengali script also writes Assamese.
Those are reported as Hindi/Marathi and Bengali; the lexicons can be extended when it matters.
"""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from app.core.lexicon import (
    ENGLISH_FUNCTION,
    HINDI_DEVANAGARI,
    MARATHI_DEVANAGARI,
    ROMAN_HINDI,
    in_lexicon,
    tokenise,
)

UNDETERMINED = "und"
SCRIPT_ONLY_CONFIDENCE = 0.4  # Devanagari with no Hindi or Marathi word to go on
FULL_CONFIDENCE_HITS = 4  # how many lexicon hits make a verdict fully confident
_BASE_CONFIDENCE = 0.4
_PER_HIT = 0.15
_UNIQUE_SCRIPT_CONFIDENCE = 0.9


class Script(StrEnum):
    LATIN = "latin"
    DEVANAGARI = "devanagari"
    BENGALI = "bengali"
    GURMUKHI = "gurmukhi"
    GUJARATI = "gujarati"
    ODIA = "odia"
    TAMIL = "tamil"
    TELUGU = "telugu"
    KANNADA = "kannada"
    MALAYALAM = "malayalam"
    UNKNOWN = "unknown"


# (first code point, last code point, script) of each Indic block.
_BLOCKS = (
    (0x0900, 0x097F, Script.DEVANAGARI),
    (0x0980, 0x09FF, Script.BENGALI),
    (0x0A00, 0x0A7F, Script.GURMUKHI),
    (0x0A80, 0x0AFF, Script.GUJARATI),
    (0x0B00, 0x0B7F, Script.ODIA),
    (0x0B80, 0x0BFF, Script.TAMIL),
    (0x0C00, 0x0C7F, Script.TELUGU),
    (0x0C80, 0x0CFF, Script.KANNADA),
    (0x0D00, 0x0D7F, Script.MALAYALAM),
)
# The languages a script settles on its own.
_SCRIPT_LANGUAGE = {
    Script.BENGALI: "bn",
    Script.GURMUKHI: "pa",
    Script.GUJARATI: "gu",
    Script.ODIA: "or",
    Script.TAMIL: "ta",
    Script.TELUGU: "te",
    Script.KANNADA: "kn",
    Script.MALAYALAM: "ml",
}


@dataclass(frozen=True)
class Detection:
    script: Script
    language: str  # ISO 639-1 code, or "und"
    confidence: float  # 0 when undetermined


def _script_of_char(char: str) -> Script:
    code = ord(char)
    for first, last, script in _BLOCKS:
        if first <= code <= last and char not in "।॥":
            # Devanagari digits and letters both count; punctuation does not.
            return script
    if char.isascii() and char.isalpha():
        return Script.LATIN
    return Script.UNKNOWN


def _script_of_token(token: str) -> Script:
    for char in token:
        script = _script_of_char(char)
        if script is not Script.UNKNOWN:
            return script
    return Script.UNKNOWN


def _script_of(tokens: tuple[str, ...]) -> Script:
    """The script most words are in, so one English word in a Hindi sentence changes nothing."""
    votes = Counter(s for s in map(_script_of_token, tokens) if s is not Script.UNKNOWN)
    if not votes:
        return Script.UNKNOWN
    return votes.most_common(1)[0][0]


def _confidence(hits: int, share: float) -> float:
    return round(min(1.0, _BASE_CONFIDENCE + _PER_HIT * hits) * share, 3)


def _latin(tokens: tuple[str, ...]) -> Detection:
    hindi = sum(in_lexicon(token, ROMAN_HINDI) for token in tokens)
    english = sum(token in ENGLISH_FUNCTION for token in tokens)
    if hindi == english:  # no evidence, or evidence that cancels out
        return Detection(Script.LATIN, UNDETERMINED, 0.0)
    winner = "hi" if hindi > english else "en"
    hits = max(hindi, english)
    share = hits / (hindi + english)
    return Detection(Script.LATIN, winner, _confidence(hits, share))


def _devanagari(tokens: tuple[str, ...]) -> Detection:
    hindi = sum(token in HINDI_DEVANAGARI for token in tokens)
    marathi = sum(token in MARATHI_DEVANAGARI for token in tokens)
    if marathi > hindi:
        return Detection(Script.DEVANAGARI, "mr", _confidence(marathi, marathi / (hindi + marathi)))
    if hindi:
        return Detection(Script.DEVANAGARI, "hi", _confidence(hindi, hindi / (hindi + marathi)))
    return Detection(Script.DEVANAGARI, "hi", SCRIPT_ONLY_CONFIDENCE)


def detect(text: str) -> Detection:
    tokens = tokenise(text)
    script = _script_of(tokens)
    if script is Script.UNKNOWN:
        return Detection(Script.UNKNOWN, UNDETERMINED, 0.0)
    if script is Script.LATIN:
        return _latin(tokens)
    if script is Script.DEVANAGARI:
        return _devanagari(tokens)
    return Detection(script, _SCRIPT_LANGUAGE[script], _UNIQUE_SCRIPT_CONFIDENCE)


_LANGUAGE_NAMES = {
    "hi": "Hindi",
    "mr": "Marathi",
    "bn": "Bengali",
    "pa": "Punjabi",
    "gu": "Gujarati",
    "or": "Odia",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
}


def wording_hint(detection: Detection) -> str | None:
    """A few words telling a model how the teacher wrote, or None when nothing needs saying.

    "Hindi typed in English letters" stops the model reading "ghatana" as an English word. Plain
    English and undetermined text need no hint.
    """
    name = _LANGUAGE_NAMES.get(detection.language)
    if name is None:
        return None
    if detection.script is Script.LATIN:
        return f"{name} typed in English letters"
    return name
