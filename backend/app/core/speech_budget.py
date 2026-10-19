"""How long a piece of text takes to say, so a voice reply never outruns its budget.

Text-to-speech output length is estimated from characters rather than measured, because the check
has to run before we pay for synthesis. The rate is deliberately on the slow side so the estimate
errs towards "too long" (Hindi with matras is the slowest case we speak).
"""

import re

SPOKEN_CHARS_PER_SECOND = 13
PLAN_BUDGET_SECONDS = 60
REFLECT_BUDGET_SECONDS = 45
MIRROR_BUDGET_SECONDS = 60
MIRROR_QUOTE_SECONDS = 25

_WHITESPACE_RUN = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[।.?!])\s+")


def _spoken(text: str) -> str:
    return _WHITESPACE_RUN.sub(" ", text).strip()


def estimated_seconds(text: str) -> float:
    return len(_spoken(text)) / SPOKEN_CHARS_PER_SECOND


def fits(text: str, budget_seconds: float) -> bool:
    return estimated_seconds(text) <= budget_seconds


def truncate_to_budget(text: str, budget_seconds: float) -> str:
    """Keep whole sentences while they fit; if even the first does not, cut at a word."""
    spoken = _spoken(text)
    if fits(spoken, budget_seconds):
        return spoken
    kept: list[str] = []
    for sentence in _SENTENCE_END.split(spoken):
        candidate = " ".join([*kept, sentence])
        if not fits(candidate, budget_seconds):
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    return _cut_at_word(spoken, budget_seconds)


def _cut_at_word(spoken: str, budget_seconds: float) -> str:
    limit = int(budget_seconds * SPOKEN_CHARS_PER_SECOND)
    clipped = spoken[:limit]
    boundary = clipped.rfind(" ")
    return clipped[:boundary] if boundary > 0 else clipped
