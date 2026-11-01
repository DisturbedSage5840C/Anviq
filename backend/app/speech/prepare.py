"""Turns the text a teacher reads into the text a voice should say.

The written reply keeps its layout (lists, labels, "Source:" lines). A voice reading that layout
aloud says "asterisk", reads URLs letter by letter and stumbles on arrows, so everything sent to
text-to-speech goes through `to_spoken` first. Pure functions only: nothing here touches a vendor.
"""

import re
from collections.abc import Iterable, Mapping

from app.guardrails.plain import (
    BOLD,
    HEADING_MARKER,
    ITALIC_STAR,
    ITALIC_UNDERSCORE,
    LEFTOVER_MARKUP,
    SYMBOLS,
)

# The most characters any supported Sarvam model accepts (bulbul:v2 is the tightest at 1500).
SPOKEN_MAX_CHARS = 1500
_SENTENCE_ENDS = ".!?।"
_PAUSE_ENDS = _SENTENCE_ENDS + ":;,"
_MIN_SENTENCE_CUT_SHARE = 2  # a sentence cut must keep at least 1/2 of the budget

_SOURCE_LINE = re.compile(r"^[ \t]*(?:source|स्रोत)[ \t]*:.*$", re.IGNORECASE | re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+")
_LIST_MARKER = re.compile(r"^[ \t]*(?:[-*•–][ \t]+)")
_MATH_SYMBOL = re.compile(r"(?<=[\s\d])([×÷+=−])(?=[\s\d])")
_PERCENT = re.compile(r"(?<=\d)[ \t]*%")
_MEASURE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)[ \t]*(cm|mm|km|kg|ml)\b")
_WHITESPACE = re.compile(r"\s+")

_MATH_WORDS: Mapping[str, Mapping[str, str]] = {
    "en": {"×": "times", "÷": "divided by", "+": "plus", "−": "minus", "=": "equals"},
    "hi": {"×": "गुणा", "÷": "भाग", "+": "जमा", "−": "घटा", "=": "बराबर"},
}
_PERCENT_WORD: Mapping[str, str] = {"en": "percent", "hi": "प्रतिशत"}
# unit -> (singular, plural) per language.
_UNIT_WORDS: Mapping[str, Mapping[str, tuple[str, str]]] = {
    "en": {
        "cm": ("centimetre", "centimetres"),
        "mm": ("millimetre", "millimetres"),
        "km": ("kilometre", "kilometres"),
        "kg": ("kilogram", "kilograms"),
        "ml": ("millilitre", "millilitres"),
    },
    "hi": {
        "cm": ("सेंटीमीटर", "सेंटीमीटर"),
        "mm": ("मिलीमीटर", "मिलीमीटर"),
        "km": ("किलोमीटर", "किलोमीटर"),
        "kg": ("किलोग्राम", "किलोग्राम"),
        "ml": ("मिलीलीटर", "मिलीलीटर"),
    },
}
_DEFAULT_LANG = "en"


def to_spoken(text: str, lang: str, max_chars: int = SPOKEN_MAX_CHARS) -> str:
    """The words a voice should say for `text`, never longer than `max_chars`."""
    if not text.strip():
        return ""
    cleaned = _SOURCE_LINE.sub("", text)
    cleaned = _URL.sub("", _LINK.sub(r"\1", cleaned))
    cleaned = SYMBOLS.sub(" ", cleaned)
    joined = _join_lines(_clean_line(line) for line in cleaned.splitlines())
    spoken = _speak_symbols(joined, lang)
    return _truncate(_WHITESPACE.sub(" ", spoken).strip(), max_chars)


def _clean_line(line: str) -> str:
    plain = HEADING_MARKER.sub("", _LIST_MARKER.sub("", line))
    plain = BOLD.sub(r"\2", plain)
    plain = ITALIC_STAR.sub(r"\1", plain)
    plain = ITALIC_UNDERSCORE.sub(r"\1", plain)
    return _WHITESPACE.sub(" ", LEFTOVER_MARKUP.sub("", plain)).strip()


def _join_lines(lines: Iterable[str]) -> str:
    """One string, with a pause between lines that do not already end in punctuation."""
    spoken = ""
    for line in lines:
        if not line:
            continue
        if spoken and spoken[-1] not in _PAUSE_ENDS:
            spoken += "."
        spoken = f"{spoken} {line}" if spoken else line
    return spoken


def _speak_symbols(text: str, lang: str) -> str:
    math = _MATH_WORDS.get(lang, _MATH_WORDS[_DEFAULT_LANG])
    percent = _PERCENT_WORD.get(lang, _PERCENT_WORD[_DEFAULT_LANG])
    units = _UNIT_WORDS.get(lang, _UNIT_WORDS[_DEFAULT_LANG])

    def measure(match: re.Match[str]) -> str:
        number, unit = match.group(1), match.group(2)
        singular, plural = units[unit]
        return f"{number} {singular if number == '1' else plural}"

    with_math = _MATH_SYMBOL.sub(lambda match: f" {math[match.group(1)]} ", text)
    with_percent = _PERCENT.sub(f" {percent}", with_math)
    return _MEASURE.sub(measure, with_percent)


def _truncate(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a sentence end if one is late enough, else at a word."""
    if len(text) <= limit:
        return text
    sentence_end = max(text.rfind(mark, 0, limit) for mark in _SENTENCE_ENDS)
    if sentence_end >= limit // _MIN_SENTENCE_CUT_SHARE:
        return text[: sentence_end + 1]
    word_end = text.rfind(" ", 0, limit + 1)
    return text[:word_end] if word_end > 0 else text[:limit]
