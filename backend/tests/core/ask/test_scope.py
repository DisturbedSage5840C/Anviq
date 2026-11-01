from collections.abc import Sequence

from app.core.ask.bm25 import Bm25Index
from app.core.ask.retrieve import HybridRetriever, Passage, Queries, Scope
from app.db.corpus import Bm25Search, ChunkRow


def _row(
    row_id: str,
    text: str,
    *,
    class_level: int | None = None,
    subject: str | None = None,
    source: str | None = None,
) -> ChunkRow:
    return ChunkRow(
        row_id, f"label {row_id}", text, None, class_level=class_level, subject=subject,
        source=source,
    )  # fmt: skip


ROWS = [
    _row("c3", "fractions of a whole shape", class_level=3, subject="mathematics", source="NCERT"),
    _row("c5", "fractions of a whole shape", class_level=5, subject="mathematics", source="NCERT"),
    _row("e3", "fractions in a story", class_level=3, subject="english", source="NCERT"),
    _row("p", "fractions teaching routine", source="NISHTHA FLN"),
]


class Loader:
    async def __call__(self, lang: str) -> Sequence[ChunkRow]:
        return ROWS


def test_an_empty_scope_admits_everything():
    scope = Scope()

    assert all(scope.admits(r.class_level, r.subject, r.source) for r in ROWS)


def test_a_class_scope_keeps_that_class_and_class_agnostic_pedagogy():
    scope = Scope(class_levels=frozenset({3}))

    kept = [r.id for r in ROWS if scope.admits(r.class_level, r.subject, r.source)]

    assert kept == ["c3", "e3", "p"]


def test_subject_and_source_narrow_further():
    scope = Scope(subjects=frozenset({"mathematics"}), sources=frozenset({"NCERT"}))

    kept = [r.id for r in ROWS if scope.admits(r.class_level, r.subject, r.source)]

    assert kept == ["c3", "c5"]


def test_ranking_inside_an_allowed_set_keeps_scores_comparable():
    index = Bm25Index([("a", "fractions whole"), ("b", "fractions whole"), ("c", "other words")])

    everything = index.rank(["fractions"], 5)
    narrowed = index.rank(["fractions"], 5, allowed=frozenset({"b"}))

    assert [h.doc_id for h in narrowed] == ["b"]
    assert narrowed[0].score == next(h.score for h in everything if h.doc_id == "b")


async def test_search_with_a_scope_never_returns_another_class():
    search = Bm25Search(Loader())

    found = await search.search("fractions whole shape", "en", 10, Scope(frozenset({5})))

    assert {p.chunk_id for p in found} == {"c5", "p"}


async def test_search_without_a_scope_is_unchanged():
    search = Bm25Search(Loader())

    found = await search.search("fractions", "en", 10)

    assert {p.chunk_id for p in found} == {"c3", "c5", "e3", "p"}


class RecordingSearch:
    def __init__(self) -> None:
        self.scopes: list[object] = []

    async def search(self, query: str, lang: str, limit: int, scope: Scope | None = None):
        self.scopes.append(scope)
        return [Passage("x", "l", "t", 0.9)]


async def test_the_retriever_hands_its_scope_to_every_search():
    searcher = RecordingSearch()
    scope = Scope(frozenset({4}))

    await HybridRetriever([searcher], 0.1).retrieve(Queries("प्रश्न", "question"), scope)

    assert searcher.scopes == [scope, scope]
