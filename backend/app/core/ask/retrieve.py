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
TOP_K = 6


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    label: str  # the citation line, built from chunk metadata at ingestion
    text: str
    score: float  # the search's own relevance score; only comparable within one search


class Search(Protocol):
    async def search(self, query: str, lang: str, limit: int) -> list[Passage]: ...


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

    async def retrieve(self, queries: Queries) -> Retrieval:
        rankings = []
        for search in self._searches:
            for lang, query in (("hi", queries.hi), ("en", queries.en)):
                if query.strip():
                    rankings.append(await search.search(query, lang, PER_SEARCH))
        passages = fuse(rankings)
        if not passages:
            return Retrieval([], None)
        if max(p.score for p in passages) < self._min_score:
            return Retrieval([], passages[0])
        return Retrieval(passages, passages[0])
