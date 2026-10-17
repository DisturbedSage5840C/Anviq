"""Word/character error rate for the Day-3 STT benchmark."""

import re
from collections.abc import Sequence

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def _normalise(text: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", text).casefold().split())


def _edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref_token in enumerate(reference, start=1):
        current = [i]
        for j, hyp_token in enumerate(hypothesis, start=1):
            substitution = previous[j - 1] + (ref_token != hyp_token)
            current.append(min(previous[j] + 1, current[j - 1] + 1, substitution))
        previous = current
    return previous[-1]


def _rate(reference: Sequence[str], hypothesis: Sequence[str]) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _edit_distance(reference, hypothesis) / len(reference)


def wer(reference: str, hypothesis: str) -> float:
    return _rate(_normalise(reference).split(), _normalise(hypothesis).split())


def cer(reference: str, hypothesis: str) -> float:
    return _rate(list(_normalise(reference)), list(_normalise(hypothesis)))
