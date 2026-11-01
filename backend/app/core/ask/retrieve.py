"""Find the corpus passages that answer a question (plan section 4.8, query steps 2-3).

Each search (full text in Hindi, full text in English, and vectors once an embedding provider is
configured) gives a ranked list; reciprocal rank fusion merges them without having to compare
their scores. The scope gate then refuses when even the best passage matches too weakly.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

RRF_K = 60
PER_SEARCH = 20
TOP_K = 10


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    label: str  # the citation line, built from chunk metadata at ingestion
    text: str
    score: float  # the search's own relevance score; only comparable within one search


@dataclass(frozen=True)
class Scope:
    """Which passages a question may draw on. An empty field means no limit on that field.

    A passage with no class or subject (NISHTHA, NIPUN, the Handbook) is not tied to one, so it
    passes the class and subject limits: asking as a Class 3 teacher still reaches the guidance.
    """

    class_levels: frozenset[int] = frozenset()
    subjects: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()

    def admits(self, class_level: int | None, subject: str | None, source: str | None) -> bool:
        if self.sources and source not in self.sources:
            return False
        if self.class_levels and class_level is not None and class_level not in self.class_levels:
            return False
        return not (self.subjects and subject is not None and subject not in self.subjects)


_CLASS_GRADES = {str(level): level for level in range(1, 6)}


def scope_for_grade(grade: str | None) -> Scope | None:
    """One class limits textbooks to that class; multi-grade or unknown limits nothing."""
    level = _CLASS_GRADES.get(grade or "")
    return None if level is None else Scope(class_levels=frozenset({level}))


class Search(Protocol):
    async def search(
        self, query: str, lang: str, limit: int, scope: Scope | None = None
    ) -> list[Passage]: ...


def fuse(rankings: Sequence[Sequence[Passage]], top_k: int = TOP_K) -> list[Passage]:
    """Reciprocal rank fusion. A passage keeps the best raw score any search gave it."""
    fused: dict[str, float] = {}
    best: dict[str, Passage] = {}
    for ranking in rankings:
        for rank, passage in enumerate(ranking, start=1):
            fused[passage.chunk_id] = fused.get(passage.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            kept = best.get(passage.chunk_id)
            if kept is None or passage.score > kept.score:
                best[passage.chunk_id] = passage
    order = sorted(fused, key=lambda cid: (-fused[cid], cid))
    return [best[cid] for cid in order[:top_k]]


@dataclass(frozen=True)
class Queries:
    hi: str
    en: str


@dataclass(frozen=True)
class Retrieval:
    passages: list[Passage]  # empty when nothing cleared the scope threshold
    nearest: Passage | None  # the best match even if too weak, to point the teacher to


class HybridRetriever:
    def __init__(self, searches: Sequence[Search], min_score: float) -> None:
        self._searches = searches
        self._min_score = min_score  # τ: tuned on eval/datasets/ask_*.jsonl

    async def retrieve(self, queries: Queries, scope: Scope | None = None) -> Retrieval:
        rankings = []
        for search in self._searches:
            for lang, query in (("hi", queries.hi), ("en", queries.en)):
                if not query.strip():
                    continue
                if scope is None:
                    rankings.append(await search.search(query, lang, PER_SEARCH))
                else:
                    rankings.append(await search.search(query, lang, PER_SEARCH, scope))
        passages = fuse(rankings)
        if not passages:
            return Retrieval([], None)
        if max(p.score for p in passages) < self._min_score:
            return Retrieval([], passages[0])
        return Retrieval(passages, passages[0])
