"""Postgres side of Ask Anviq: store corpus chunks and search them.

`doc_chunks` is public reference material (NISHTHA / NIPUN), not teacher data. Production search
is `Bm25Search`, which ranks the whole corpus in memory (`postgres_bm25_search` loads it). The
older `search_chunks` / `PostgresFullTextSearch` path (an OR of the question's words ranked with
ts_rank_cd over the generated 'simple' `tsv` column) is kept for the tests that still use it.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.ask.bm25 import Bm25Index, tokenize
from app.core.ask.chunking import Chunk
from app.core.ask.retrieve import Passage, Scope

# Words that appear in nearly every passage. Left in an OR query they let generic passages
# outrank the ones about the topic, so they are dropped unless the question is made of nothing else.
_FILLER_WORDS = frozenset(
    """
    a an the of in on at to for from by with and or as is are was were be been do does did can could
    should would will shall may might must how what when where which who whom why that this these
    those it its i me my we our you your they their there here not no if so than then also about
    into
    के में का की को से है हैं था थे थी और या कि पर ने भी ही तो यह इस ये वह उस वे एक कुछ जब कैसे
    क्या क्यों कौन किस कहाँ करें करना करने कर सकते सकता सकती वाला वाली वाले लिए द्वारा जैसे अपने
    """.split()
)


def content_words(question: str) -> tuple[str, ...]:
    """The question's distinct words minus filler; filler stays if that is all there is."""
    words = tuple(dict.fromkeys(tokenize(question)))
    content = tuple(w for w in words if w not in _FILLER_WORDS)
    return content or words


def or_query(question: str) -> str:
    """A tsquery string matching any content word of the question; only word characters survive."""
    return " | ".join(content_words(question))


ChunkGroup = tuple[str | int | None, ...]  # ("book", code) or ("course", source, no)

_INSERT = text(
    "insert into doc_chunks (source, course_no, module, section_no, section_title, page, lang, "
    "text, context_line, label, class_level, subject, book_code, chapter_no, chapter_title) "
    "values (:source, :course_no, :module, :section_no, :section_title, :page, :lang, :text, "
    ":context_line, :label, :class_level, :subject, :book_code, :chapter_no, :chapter_title)"
)
_DELETE_BOOK = text("delete from doc_chunks where book_code = :book_code")
_DELETE_COURSE = text(
    "delete from doc_chunks where book_code is null and source = :source "
    "and course_no is not distinct from :course_no"
)


def groups_of(chunks: Sequence[Chunk]) -> tuple[ChunkGroup, ...]:
    """The books and courses these chunks belong to, in first-seen order, without repeats."""
    seen: dict[ChunkGroup, None] = {}
    for c in chunks:
        key: ChunkGroup = (
            ("book", c.book_code) if c.book_code is not None else ("course", c.source, c.course_no)  # type: ignore[assignment]
        )
        seen.setdefault(key, None)
    return tuple(seen)


def _chunk_row(c: Chunk, context: str | None) -> dict[str, object]:
    return {
        "source": c.source,
        "course_no": c.course_no,
        "module": c.module,
        "section_no": c.section_no,
        "section_title": c.section_title,
        "page": c.page,
        "lang": c.lang,
        "text": c.text,
        "context_line": context,
        "label": c.label(),
        "class_level": c.class_level,
        "subject": c.subject,
        "book_code": c.book_code,
        "chapter_no": c.chapter_no,
        "chapter_title": c.chapter_title,
    }


async def store_chunks(
    conn: AsyncConnection, chunks: Sequence[Chunk], context_lines: Sequence[str | None]
) -> int:
    """Insert chunks with their one-line retrieval context. Returns how many were written."""
    rows = [_chunk_row(c, context) for c, context in zip(chunks, context_lines, strict=True)]
    if not rows:
        return 0
    await conn.execute(_INSERT, rows)
    return len(rows)


async def replace_chunks(
    conn: AsyncConnection, chunks: Sequence[Chunk], context_lines: Sequence[str | None]
) -> int:
    """Re-ingest: delete every row of the books or courses present, then insert the new ones.

    Runs on the caller's connection, so inside one transaction a failed insert rolls the delete
    back and a half-ingested book never replaces a good one. Without this, ingesting a book
    twice stored every chunk twice.
    """
    if not chunks:
        return 0
    for group in groups_of(chunks):
        if group[0] == "book":
            await conn.execute(_DELETE_BOOK, {"book_code": group[1]})
        else:
            await conn.execute(_DELETE_COURSE, {"source": group[1], "course_no": group[2]})
    return await store_chunks(conn, chunks, context_lines)


async def search_chunks(conn: AsyncConnection, query: str, lang: str, limit: int) -> list[Passage]:
    tsquery = or_query(query)
    if not tsquery:
        return []
    rows = await conn.execute(
        text(
            "select id, label, text, ts_rank_cd(tsv, to_tsquery('simple', :q), 32) as score "
            "from doc_chunks where lang = :lang and tsv @@ to_tsquery('simple', :q) "
            "order by score desc, id limit :limit"
        ),
        {"q": tsquery, "lang": lang, "limit": limit},
    )
    return [Passage(str(r.id), r.label, r.text, float(r.score)) for r in rows]


class PostgresFullTextSearch:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def search(
        self, query: str, lang: str, limit: int, scope: Scope | None = None
    ) -> list[Passage]:
        if scope is not None:
            raise NotImplementedError("scoped search needs Bm25Search; this path is legacy")
        async with self._engine.connect() as conn:
            return await search_chunks(conn, query, lang, limit)


@dataclass(frozen=True)
class ChunkRow:
    id: str
    label: str
    text: str
    context_line: str | None
    class_level: int | None = None
    subject: str | None = None
    source: str | None = None


ChunkLoader = Callable[[str], Awaitable[Sequence[ChunkRow]]]


class Bm25Search:
    """BM25 over the whole corpus, which is small enough to hold in memory.

    Each language is loaded on first use and kept, so after re-ingesting the corpus the API has
    to be restarted. The label and context line are indexed too, but only the chunk text is shown.
    """

    def __init__(self, load: ChunkLoader) -> None:
        self._load = load
        self._loaded: dict[str, tuple[Bm25Index, dict[str, ChunkRow]]] = {}
        self._lock = asyncio.Lock()

    async def search(
        self, query: str, lang: str, limit: int, scope: Scope | None = None
    ) -> list[Passage]:
        terms = content_words(query)
        if not terms:
            return []
        index, rows = await self._index_for(lang)
        allowed = None if scope is None else _admitted(rows, scope)
        return [
            Passage(hit.doc_id, rows[hit.doc_id].label, rows[hit.doc_id].text, hit.score)
            for hit in index.rank(terms, limit, allowed)
        ]

    async def _index_for(self, lang: str) -> tuple[Bm25Index, dict[str, ChunkRow]]:
        if lang in self._loaded:
            return self._loaded[lang]
        async with self._lock:
            if lang in self._loaded:
                return self._loaded[lang]
            rows = await self._load(lang)
            index = Bm25Index(
                [(r.id, " ".join(filter(None, (r.text, r.context_line, r.label)))) for r in rows]
            )
            loaded = (index, {r.id: r for r in rows})
            if rows:  # an empty corpus is not kept, so rows ingested later are picked up
                self._loaded[lang] = loaded
            return loaded


def _admitted(rows: dict[str, ChunkRow], scope: Scope) -> frozenset[str]:
    return frozenset(
        row_id
        for row_id, row in rows.items()
        if scope.admits(row.class_level, row.subject, row.source)
    )


def postgres_bm25_search(engine: AsyncEngine) -> Bm25Search:
    async def load(lang: str) -> list[ChunkRow]:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select id, label, text, context_line, class_level, subject, source "
                    "from doc_chunks where lang = :lang"
                ),
                {"lang": lang},
            )
            return [
                ChunkRow(
                    str(r.id), r.label, r.text, r.context_line, r.class_level, r.subject, r.source
                )
                for r in rows
            ]

    return Bm25Search(load)
