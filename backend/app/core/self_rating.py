"""Week B of the coaching cycle: the teacher rates their own question before the coach does.

Plan section 3.1: in the faded week the coach first asks "How would you rate that question?" and
only then says what it saw, because judging your own question is what builds independence. The
rating is a growth word (sprout, leaf, tree), never a number, like everything else the coach
shows (section 4.7). The words are spelled out rather than drawn as plants so that screen
readers, voice notes and older phones all say the same thing.
"""

import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

from app.content.copy import render
from app.core.mirror import Growth, growth_label


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).casefold()


_ORDER = (Growth.SPROUT, Growth.LEAF, Growth.TREE)
_RAW_RATINGS = {
    "1": Growth.SPROUT,
    "2": Growth.LEAF,
    "3": Growth.TREE,
    "१": Growth.SPROUT,  # Devanagari digits
    "२": Growth.LEAF,
    "३": Growth.TREE,
    "sprout": Growth.SPROUT,
    "leaf": Growth.LEAF,
    "tree": Growth.TREE,
    "अंकुर": Growth.SPROUT,
    "पत्ती": Growth.LEAF,
    "पेड़": Growth.TREE,
    # Earlier versions of the prompt asked for a plant; a teacher may still send one back.
    "\U0001f331": Growth.SPROUT,
    "\U0001f33f": Growth.LEAF,
    "\U0001f333": Growth.TREE,
}
# Indic keyboards differ on precomposed versus base-plus-nukta letters; compare in NFC.
_RATINGS: Mapping[str, Growth] = MappingProxyType(
    {_fold(key): growth for key, growth in _RAW_RATINGS.items()}
)


def parse_rating(text: str) -> Growth | None:
    """The level the teacher chose, if the whole message is a digit 1-3 or a growth word."""
    return _RATINGS.get(_fold(text))


def rating_prompt(lang: str) -> str:
    return render("self_rating_prompt", lang)


def compare(mine: Growth, coach: Growth, lang: str) -> str:
    """One line setting the teacher's own rating beside the coach's."""
    gap = _ORDER.index(mine) - _ORDER.index(coach)
    if gap == 0:
        key = "self_rating_same"
    else:
        key = "self_rating_higher" if gap > 0 else "self_rating_lower"
    return render(key, lang).format(mine=growth_label(mine, lang), coach=growth_label(coach, lang))
