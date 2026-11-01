"""Spelling misconceptions: writing words by sound, plurals, and endings."""

import re

from app.core.children.malrules.base import Malrule
from app.core.children.malrules.lexicon import (
    DOUBLED_CONSONANT_WORDS,
    PHONETIC_SPELLINGS,
    PLURAL_Y_WORDS,
    SILENT_E_WORDS,
)
from app.core.children.problem import Kind, Problem

TOPIC_SOUND = "LIT.G3.SPELL_SOUND"
TOPIC_PLURAL = "LIT.G4.SPELL_PLURAL"
TOPIC_SUFFIX = "LIT.G5.SPELL_SUFFIX"
SOURCE = "Spelling-development research on common errors; pending expert review"
_DOUBLED = re.compile(r"^(.*[aeiou])([a-z])\2(ing|ed)$")


def _spelling(p: Problem, words: object) -> bool:
    return p.kind is Kind.SPELL_WORD and p.text in words  # type: ignore[operator]


def _by_sound_case(p: Problem) -> bool:
    return _spelling(p, PHONETIC_SPELLINGS)


def _by_sound(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = (
        "says the word and writes down only the sounds heard",
        "does not remember the odd letters",
    )
    return PHONETIC_SPELLINGS[p.text], steps


def _plural_case(p: Problem) -> bool:
    return _spelling(p, PLURAL_Y_WORDS)


def _plural(p: Problem) -> tuple[str, tuple[str, ...]]:
    singular = p.text[:-3] + "y"
    steps = (f"takes {singular} and adds s as for any other word", "does not change the y to i")
    return singular + "s", steps


def _doubled_case(p: Problem) -> bool:
    return _spelling(p, DOUBLED_CONSONANT_WORDS) and _DOUBLED.match(p.text) is not None


def _doubled(p: Problem) -> tuple[str, tuple[str, ...]]:
    match = _DOUBLED.match(p.text)
    assert match is not None  # `applies` checked  # noqa: S101
    stem, consonant, ending = match.groups()
    steps = (f"adds {ending} straight onto the word", f"forgets to write {consonant} twice")
    return stem + consonant + ending, steps


def _silent_e_case(p: Problem) -> bool:
    return _spelling(p, SILENT_E_WORDS)


def _silent_e(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = ("adds ing to the whole word", "does not drop the silent e")
    return p.text[:-3] + "e" + "ing", steps


BY_SOUND = Malrule(
    "SPELL.BY_SOUND", (TOPIC_SOUND,), (3, 4), SOURCE,
    "Spells a word exactly as it sounds, so friend is written frend.",
    _by_sound_case, _by_sound,
)  # fmt: skip
PLURAL_Y = Malrule(
    "SPELL.PLURAL_Y", (TOPIC_PLURAL,), (4, 5), SOURCE,
    "Adds s to a word ending in y, so babies is written babys.",
    _plural_case, _plural,
)  # fmt: skip
DOUBLE_DROP = Malrule(
    "SPELL.DOUBLE_DROP", (TOPIC_SUFFIX,), (5,), SOURCE,
    "Does not double the last letter before -ing or -ed, so running is written runing.",
    _doubled_case, _doubled,
)  # fmt: skip
SILENT_E_KEPT = Malrule(
    "SPELL.SILENT_E_KEPT", (TOPIC_SUFFIX,), (5,), SOURCE,
    "Keeps the silent e before -ing, so hoping is written hopeing.",
    _silent_e_case, _silent_e,
)  # fmt: skip

RULES = (BY_SOUND, PLURAL_Y, DOUBLE_DROP, SILENT_E_KEPT)
