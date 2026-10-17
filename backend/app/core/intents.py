"""Deterministic Hindi/English intent parsing: the free, instant first stage of the router.

Anything these functions return None for falls through to the next stage (an LLM classifier,
added with the planner) or to the current state's default.
"""

import re
import unicodedata
from enum import StrEnum

# Devanagari block minus the danda (U+0964) and double danda (U+0965), which are punctuation.
_TOKEN = re.compile(r"[\w\u0900-\u0963\u0966-\u097F]+")
SHORT_UTTERANCE_MAX_TOKENS = 3


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(_normalise(text)))


def _phrases(*phrases: str) -> tuple[tuple[str, ...], ...]:
    return tuple(_tokens(phrase) for phrase in phrases)


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(tokens[i : i + width] == phrase for i in range(len(tokens) - width + 1))


class GlobalIntent(StrEnum):
    DELETE = "delete"
    STOP = "stop"
    PRIVACY = "privacy"
    HELP = "help"


_DELETE = _phrases(
    "मेरा डेटा मिटाओ",
    "डेटा मिटाओ",
    "मेरा डाटा मिटाओ",
    "delete my data",
    "delete my account",
    "erase my data",
)
_PRIVACY = _phrases("कौन देखता है", "कौन देखती है", "who sees", "privacy", "प्राइवेसी")
# "stop" and "help" are everyday words in a classroom, so they only count as commands when the
# whole utterance is short.
_STOP = _phrases("बंद करो", "बंद", "stop", "unsubscribe")
_HELP = _phrases("मदद", "help")


def _matches_any(tokens: tuple[str, ...], phrases: tuple[tuple[str, ...], ...]) -> bool:
    return any(_contains_phrase(tokens, phrase) for phrase in phrases)


def classify_global(text: str) -> GlobalIntent | None:
    """Intents that apply in any state, checked before anything else. Delete outranks the rest."""
    tokens = _tokens(text)
    if _matches_any(tokens, _DELETE):
        return GlobalIntent.DELETE
    if _matches_any(tokens, _PRIVACY):
        return GlobalIntent.PRIVACY
    if len(tokens) <= SHORT_UTTERANCE_MAX_TOKENS:
        if _matches_any(tokens, _STOP):
            return GlobalIntent.STOP
        if _matches_any(tokens, _HELP):
            return GlobalIntent.HELP
    return None


_YES = frozenset(_tokens("हाँ हां हा जी ठीक सही yes y ok okay sure yeah yep"))
_NO = frozenset(_tokens("नहीं नही ना no n nope"))


def parse_yes_no(text: str) -> bool | None:
    tokens = set(_tokens(text))
    if tokens & _NO:
        return False
    if tokens & _YES:
        return True
    return None


_LANGUAGES = {
    "hi": frozenset(_tokens("hindi हिंदी हिन्दी")),
    "en": frozenset(_tokens("english अंग्रेजी अंग्रेज़ी इंग्लिश")),
}


def parse_language(text: str) -> str | None:
    tokens = set(_tokens(text))
    for code, words in _LANGUAGES.items():
        if tokens & words:
            return code
    return None


_GRADE_WORDS = {
    "1": _tokens("1 १ one एक पहली first"),
    "2": _tokens("2 २ two दो दूसरी second"),
    "3": _tokens("3 ३ three तीन तीसरी third"),
}
_MULTI_WORDS = frozenset(_tokens("mixed multigrade multi-grade मिली मिलीजुली मिश्रित"))


def parse_grade(text: str) -> str | None:
    tokens = set(_tokens(text))
    found = [grade for grade, words in _GRADE_WORDS.items() if tokens & set(words)]
    if len(found) > 1 or (tokens & _MULTI_WORDS):
        return "multi"
    return found[0] if found else None
