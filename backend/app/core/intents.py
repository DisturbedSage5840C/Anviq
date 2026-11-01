"""Deterministic Hindi/English intent parsing: the free, instant first stage of the router.

Anything these functions return None for falls through to the next stage (an LLM classifier,
added with the planner) or to the current state's default.
"""

from enum import StrEnum

from app.core.lexicon import (
    QUESTION_WORDS_OTHER,
    ROMAN_NO,
    ROMAN_QUESTION,
    ROMAN_YES,
    in_lexicon,
    squeezed,
    tokenise,
)

SHORT_UTTERANCE_MAX_TOKENS = 3
# Saving recordings needs a clear yes, so the opt-in must be a short message, not a phrase buried
# in a longer sentence.
CLIPS_OPT_IN_MAX_TOKENS = 8
QUESTION_MIN_TOKENS = 3
# "haan" and "nahi" typed in English letters answer a yes/no prompt only when that is all the
# message is. "bacche nahi samajhte jab main ghatana sikhati hoon" is a teacher describing a
# problem, and a stray "no" must never read as refusing consent.
ROMAN_ANSWER_MAX_TOKENS = 4

_tokens = tokenise


def _phrases(*phrases: str) -> tuple[tuple[str, ...], ...]:
    return tuple(_tokens(phrase) for phrase in phrases)


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(tokens[i : i + width] == phrase for i in range(len(tokens) - width + 1))


class GlobalIntent(StrEnum):
    DELETE = "delete"
    WITHDRAW_CONSENT = "withdraw_consent"
    EXPORT = "export"
    CLIPS_ON = "clips_on"
    CLIPS_OFF = "clips_off"
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
_WITHDRAW_CONSENT = _phrases(
    "सहमति वापस",
    "withdraw consent",
    "withdraw my consent",
    "revoke consent",
    "revoke my consent",
)
_EXPORT = _phrases(
    "मेरा डेटा भेजो",
    "डेटा भेजो",
    "मेरा डाटा भेजो",
    "send me my data",
    "export my data",
    "download my data",
)
# Opting in is a separate, explicit yes to keeping practice recordings; "don't keep my recordings"
# contains "keep my recordings", so the opt-out is always checked first.
_CLIPS_OFF = _phrases(
    "stop saving my recordings",
    "stop saving recordings",
    "stop keeping my recordings",
    "stop recordings",
    "don't keep my recordings",
    "do not keep my recordings",
    "delete my recordings",
    "delete my clips",
    "रिकॉर्डिंग मत रखो",
    "रिकॉर्डिंग मत सेव करो",
    "रिकॉर्डिंग मिटाओ",
    "रिकॉर्डिंग हटाओ",
)
_CLIPS_ON = _phrases(
    "save my recordings",
    "keep my recordings",
    "save my practice recordings",
    "keep my practice recordings",
    "रिकॉर्डिंग सेव करो",
    "रिकॉर्डिंग रखो",
)
# Any of these next to a mention of recordings means "no", whatever else the sentence says:
# "don't save my recordings" must never read as an opt-in. "don" and "t" are what the tokeniser
# leaves of "don't"; "t" only ever comes from a contraction.
_NEGATIONS = frozenset({"not", "no", "never", "don", "dont", "t", "without", "मत", "नहीं", "नही"})
_CLIP_SUBJECTS = frozenset({"recording", "recordings", "clip", "clips", "रिकॉर्डिंग"})
_PRIVACY = _phrases("कौन देखता है", "कौन देखती है", "who sees", "privacy", "प्राइवेसी")
# "stop" and "help" are everyday words in a classroom, so they only count as commands when the
# whole utterance is short.
_STOP = _phrases("बंद करो", "बंद", "stop", "unsubscribe")
_HELP = _phrases("मदद", "help")


def _matches_any(tokens: tuple[str, ...], phrases: tuple[tuple[str, ...], ...]) -> bool:
    return any(_contains_phrase(tokens, phrase) for phrase in phrases)


def _negates_clips(tokens: tuple[str, ...]) -> bool:
    """A negation word in a sentence about recordings: when unsure, nothing is kept."""
    return not _NEGATIONS.isdisjoint(tokens) and not _CLIP_SUBJECTS.isdisjoint(tokens)


def classify_global(text: str) -> GlobalIntent | None:
    """Intents that apply in any state, checked before anything else. Delete outranks the rest."""
    tokens = _tokens(text)
    if _matches_any(tokens, _DELETE):
        return GlobalIntent.DELETE
    if _matches_any(tokens, _WITHDRAW_CONSENT):
        return GlobalIntent.WITHDRAW_CONSENT
    if _matches_any(tokens, _EXPORT):
        return GlobalIntent.EXPORT
    if _matches_any(tokens, _CLIPS_OFF) or _negates_clips(tokens):
        return GlobalIntent.CLIPS_OFF
    if len(tokens) <= CLIPS_OPT_IN_MAX_TOKENS and _matches_any(tokens, _CLIPS_ON):
        return GlobalIntent.CLIPS_ON
    if _matches_any(tokens, _PRIVACY):
        return GlobalIntent.PRIVACY
    if len(tokens) <= SHORT_UTTERANCE_MAX_TOKENS:
        if _matches_any(tokens, _STOP):
            return GlobalIntent.STOP
        if _matches_any(tokens, _HELP):
            return GlobalIntent.HELP
    return None


class MenuIntent(StrEnum):
    PLAN = "plan"
    REFLECT = "reflect"
    MIRROR = "mirror"
    ASK = "ask"
    REHEARSE = "rehearse"


_MENU_WORDS = {
    MenuIntent.PLAN: frozenset(_tokens("plan प्लान")),
    MenuIntent.REFLECT: frozenset(_tokens("reflect रिफ्लेक्ट")),
    MenuIntent.MIRROR: frozenset(_tokens("mirror मिरर")),
    MenuIntent.ASK: frozenset(_tokens("ask question सवाल प्रश्न पूछो")),
    MenuIntent.REHEARSE: frozenset(_tokens("rehearse rehearsal रिहर्सल")),
}


def classify_menu(text: str) -> MenuIntent | None:
    """Menu choices. Only short messages count: "plan" inside a lesson description is content."""
    tokens = _tokens(text)
    if len(tokens) > SHORT_UTTERANCE_MAX_TOKENS:
        return None
    for intent, words in _MENU_WORDS.items():
        if words.intersection(tokens):
            return intent
    return None


# English puts the question word first; Hindi puts it anywhere ("बच्चे घटाना क्यों नहीं सीख पाते").
_ENGLISH_OPENERS = frozenset(_tokens("how what why when where which who whom"))
_HINDI_QUESTION_WORDS = frozenset(_tokens("क्या कैसे कैसी क्यों कब कहाँ कहां कौन कितना कितने कितनी किस"))
# Question words of Hindi typed in English letters, and of the other Indian scripts.
_OTHER_QUESTION_WORDS = ROMAN_QUESTION | QUESTION_WORDS_OTHER


def looks_like_question(text: str) -> bool:
    """A real question, not a fragment: ends in "?", opens with an English wh-/how word, or has
    a Hindi question word anywhere, in Devanagari or typed in English letters, or a question word
    of another Indian script (Marathi, Tamil, Bengali and so on).

    Auxiliary openers ("do", "is", "can") are left out: "do not worry" is a statement, and each
    question costs two model calls. Needs a few words, so "what?" falls through to the menu.
    """
    tokens = _tokens(text)
    if len(tokens) < QUESTION_MIN_TOKENS:
        return False
    return (
        text.rstrip().endswith(("?", "？"))
        or tokens[0] in _ENGLISH_OPENERS
        or not _HINDI_QUESTION_WORDS.isdisjoint(tokens)
        or any(in_lexicon(token, _OTHER_QUESTION_WORDS) for token in tokens)
    )


_YES = frozenset(_tokens("हाँ हां हा जी ठीक सही yes y ok okay sure yeah yep"))
_NO = frozenset(_tokens("नहीं नही ना no n nope"))


def _says(tokens: tuple[str, ...], native: frozenset[str], roman: frozenset[str]) -> bool:
    if not native.isdisjoint(tokens):
        return True
    if len(tokens) > ROMAN_ANSWER_MAX_TOKENS:
        return False
    return any(in_lexicon(token, roman) for token in tokens)


def parse_yes_no(text: str) -> bool | None:
    """True for yes, False for no, None when it is neither. No outranks yes ("haan par nahi").

    Handles stretched letters ("yeees", "haaan"); romanized Hindi counts only in a short reply.
    """
    tokens = _tokens(text)
    stretched = frozenset(form for token in tokens for form in squeezed(token))
    if _says(tokens, _NO, ROMAN_NO) or not _NO.isdisjoint(stretched):
        return False
    if _says(tokens, _YES, ROMAN_YES) or not _YES.isdisjoint(stretched):
        return True
    return None


_LANGUAGES = {
    "hi": frozenset(_tokens("hindi हिंदी हिन्दी")),
    "en": frozenset(_tokens("english angrezi angreji inglish अंग्रेजी अंग्रेज़ी इंग्लिश")),
}


def parse_language(text: str) -> str | None:
    """An explicit request for a language ("Hindi please"). Detection never calls this."""
    tokens = {form for token in _tokens(text) for form in squeezed(token)}
    for code, words in _LANGUAGES.items():
        if tokens & words:
            return code
    return None


_GRADE_WORDS = {
    "1": _tokens("1 १ one एक पहली first"),
    "2": _tokens("2 २ two दो दूसरी second"),
    "3": _tokens("3 ३ three तीन तीसरी third"),
    "4": _tokens("4 ४ four चार चौथी fourth"),
    "5": _tokens("5 ५ five पाँच पांच पाँचवीं पांचवीं पाँचवी पांचवी fifth"),
}
_MULTI_WORDS = frozenset(_tokens("mixed multigrade multi-grade मिली मिलीजुली मिश्रित"))


def parse_grade(text: str) -> str | None:
    tokens = set(_tokens(text))
    found = [grade for grade, words in _GRADE_WORDS.items() if tokens & set(words)]
    if len(found) > 1 or (tokens & _MULTI_WORDS):
        return "multi"
    return found[0] if found else None
