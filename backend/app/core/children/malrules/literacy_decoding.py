"""Early-reading misconceptions: look-alike letters, blending, and sight words."""

from app.core.children.malrules.base import Malrule
from app.core.children.malrules.lexicon import (
    BD_WORDS,
    CVC_WORDS,
    HINDI_BV_WORDS,
    REVERSED_WORDS,
    SHAPE_GUESSES,
    VOWELS,
)
from app.core.children.problem import Kind, Problem

TOPIC_LETTERS = "LIT.G1.LETTER_SOUND"
TOPIC_BLEND = "LIT.G1.BLEND"
TOPIC_SIGHT = "LIT.G2.SIGHT_WORDS"
SOURCE = "Early-reading research on decoding errors; pending expert review"
_NEXT_VOWEL = {"a": "e", "e": "i", "i": "o", "o": "u", "u": "a"}
_BD_SWAP = str.maketrans("bd", "db")
_BV_SWAP = str.maketrans("बव", "वब")


def _reading(p: Problem) -> bool:
    return p.kind is Kind.READ_WORD and bool(p.text)


def _bd_case(p: Problem) -> bool:
    return _reading(p) and p.text in BD_WORDS


def _bd(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = ("sees b and d as the same shape", "reads each of them the wrong way round")
    return p.text.translate(_BD_SWAP), steps


def _bv_case(p: Problem) -> bool:
    return _reading(p) and p.text in HINDI_BV_WORDS


def _bv(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = ("mixes up ब and व", "reads each of them as the other letter")
    return p.text.translate(_BV_SWAP), steps


def _is_cvc(p: Problem) -> bool:
    text = p.text
    return (
        _reading(p)
        and text in CVC_WORDS
        and len(text) == 3
        and text[1] in VOWELS
        and text[0] not in VOWELS
        and text[2] not in VOWELS
    )


def _drop_final(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = ("sounds out the first two letters", "stops before the last sound")
    return p.text[:-1], steps


def _vowel_swap(p: Problem) -> tuple[str, tuple[str, ...]]:
    vowel = p.text[1]
    steps = (
        "reads the first and last letters correctly",
        f"says the vowel {_NEXT_VOWEL[vowel]} instead of {vowel}",
    )
    return p.text[0] + _NEXT_VOWEL[vowel] + p.text[2], steps


def _reversal_case(p: Problem) -> bool:
    return _reading(p) and p.text in REVERSED_WORDS


def _reversal(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = ("reads the word from the right, last letter first",)
    return REVERSED_WORDS[p.text], steps


def _shape_case(p: Problem) -> bool:
    return _reading(p) and p.text in SHAPE_GUESSES


def _shape(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = (
        "looks only at how the word starts and how long it is",
        "guesses a word that looks similar",
    )
    return SHAPE_GUESSES[p.text], steps


BD_REVERSAL = Malrule(
    "LIT.BD_REVERSAL", (TOPIC_LETTERS,), (1, 2), SOURCE,
    "Swaps b and d when reading, so bed is read as deb.",
    _bd_case, _bd,
)  # fmt: skip
BV_SWAP_HI = Malrule(
    "LIT.BV_SWAP_HI", (TOPIC_LETTERS,), (1, 2), SOURCE,
    "Swaps the look-alike Hindi letters ब and व when reading.",
    _bv_case, _bv,
)  # fmt: skip
DROP_FINAL_SOUND = Malrule(
    "LIT.DROP_FINAL_SOUND", (TOPIC_BLEND,), (1,), SOURCE,
    "Reads a short word without its last sound, so cat is read as ca.",
    _is_cvc, _drop_final,
)  # fmt: skip
VOWEL_SWAP = Malrule(
    "LIT.VOWEL_SWAP", (TOPIC_BLEND,), (1,), SOURCE,
    "Gets the consonants right but says the wrong vowel, so cat is read as cet.",
    _is_cvc, _vowel_swap,
)  # fmt: skip
WORD_REVERSAL = Malrule(
    "LIT.WORD_REVERSAL", (TOPIC_SIGHT,), (1, 2), SOURCE,
    "Reads a word back to front, so was is read as saw.",
    _reversal_case, _reversal,
)  # fmt: skip
SHAPE_GUESS = Malrule(
    "LIT.SHAPE_GUESS", (TOPIC_SIGHT,), (2, 3), SOURCE,
    "Guesses a word from its first letter and length, so what is read as want.",
    _shape_case, _shape,
)  # fmt: skip

RULES = (BD_REVERSAL, BV_SWAP_HI, DROP_FINAL_SOUND, VOWEL_SWAP, WORD_REVERSAL, SHAPE_GUESS)
