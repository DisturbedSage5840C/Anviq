"""BM25 ranking over a small in-memory corpus.

Postgres full-text ranking has no notion of how rare a word is, so a generic "course overview"
page that repeats words like "teaching" and "approach" outranks the passage that holds the one
rare word the question is about. BM25 weights each query word by its rarity (idf). The corpus is
a few thousand chunks, so scoring it in memory is cheap and needs no extra service.

The score is divided by the best score a passage could reach for this query, giving a 0..1 value.
It only says how much of the query a passage covers; it cannot tell an in-scope question from an
out-of-scope one, so scope is decided by the question rewrite and this stays a low floor.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

# Devanagari U+0900-U+097F except the danda and double danda (U+0964, U+0965), which end sentences.
_WORD = re.compile(r"[0-9A-Za-z\u0900-\u0963\u0966-\u097F]+")
MIN_WORD_CHARS = 2
K1 = 1.2  # how quickly repeated occurrences of a word stop adding score
B = 0.75  # how strongly long passages are discounted


def tokenize(text: str) -> list[str]:
    """Lower-cased words of two or more characters; works for Hindi and English alike."""
    return [w.casefold() for w in _WORD.findall(text) if len(w) >= MIN_WORD_CHARS]


@dataclass(frozen=True)
class Hit:
    doc_id: str
    score: float  # 0..1, a share of the best attainable score for the query


class Bm25Index:
    def __init__(self, docs: Sequence[tuple[str, str]]) -> None:
        self._ids = [doc_id for doc_id, _ in docs]
        self._counts = [Counter(tokenize(text)) for _, text in docs]
        self._lengths = [sum(c.values()) for c in self._counts]
        self._avg_length = (sum(self._lengths) / len(docs)) if docs else 0.0
        document_frequency: Counter[str] = Counter()
        for counts in self._counts:
            document_frequency.update(counts.keys())
        total = len(docs)
        self._idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def rank(self, terms: Sequence[str], limit: int) -> list[Hit]:
        """The best `limit` passages sharing at least one term, best first (ties by id)."""
        unique = [t for t in dict.fromkeys(terms) if t in self._idf]
        if not unique or limit <= 0:
            return []
        best_possible = sum(self._idf[t] * (K1 + 1) for t in unique)
        scored = [(self._score(i, unique) / best_possible, i) for i in range(len(self._ids))]
        hits = [Hit(self._ids[i], s) for s, i in scored if s > 0]
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits[:limit]

    def _score(self, index: int, terms: Sequence[str]) -> float:
        counts = self._counts[index]
        length_norm = 1 - B + B * self._lengths[index] / self._avg_length
        total = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if tf:
                total += self._idf[term] * tf * (K1 + 1) / (tf + K1 * length_norm)
        return total
