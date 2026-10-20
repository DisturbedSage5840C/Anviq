"""Week B of the coaching cycle: the teacher rates their own question before the coach does.

Plan section 3.1: in the faded week the coach first asks "How would you rate that question?" and
only then says what it saw, because judging your own question is what builds independence. The
rating is a plant, never a number, like everything else the coach shows (section 4.7).
"""

from collections.abc import Mapping
from types import MappingProxyType

from app.content.copy import render
from app.core.mirror import Growth

_ORDER = (Growth.SPROUT, Growth.LEAF, Growth.TREE)
_RATINGS: Mapping[str, Growth] = MappingProxyType(
    {
        "1": Growth.SPROUT,
        "2": Growth.LEAF,
        "3": Growth.TREE,
        "१": Growth.SPROUT,  # Devanagari digits
        "२": Growth.LEAF,
        "३": Growth.TREE,
        "🌱": Growth.SPROUT,
        "🌿": Growth.LEAF,
        "🌳": Growth.TREE,
    }
)


def parse_rating(text: str) -> Growth | None:
    """The plant the teacher chose, if the whole message is one digit 1-3 or one plant."""
    return _RATINGS.get(text.strip())


def rating_prompt(lang: str) -> str:
    return render("self_rating_prompt", lang)


def compare(mine: Growth, coach: Growth, lang: str) -> str:
    """One line setting the teacher's own rating beside the coach's."""
    gap = _ORDER.index(mine) - _ORDER.index(coach)
    if gap == 0:
        key = "self_rating_same"
    else:
        key = "self_rating_higher" if gap > 0 else "self_rating_lower"
    return render(key, lang).format(mine=mine.value, coach=coach.value)
