"""Postgres side of Ask Anviq: store corpus chunks and search them by full text.

`doc_chunks` is public reference material (NISHTHA / NIPUN), not teacher data. The `tsv` column
is generated with the 'simple' configuration, which works for Hindi and English alike because it
does no stemming. Questions are searched as an OR of their words, ranked with ts_rank_cd and
squashed to 0..1 so a single threshold can gate scope.
"""

import re
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.ask.chunking import Chunk
from app.core.ask.retrieve import Passage

_WORD = re.compile(r"[0-9A-Za-zऀ-ॿ]+")
MIN_WORD_CHARS = 2


def or_query(question: str) -> str:
    """A tsquery string matching any word of the question; safe because only word chars survive."""
    words = dict.fromkeys(w.casefold() for w in _WORD.findall(question) if len(w) >= MIN_WORD_CHARS)
    return " | ".join(words)


async def store_chunks(
    conn: AsyncConnection, chunks: Sequence[Chunk], context_lines: Sequence[str | None]
) -> int:
    """Insert chunks with their one-line retrieval context. Returns how many were written."""
    rows = [
        {
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
        }
        for c, context in zip(chunks, context_lines, strict=True)
    ]
    if not rows:
        return 0
    await conn.execute(
        text(
            "insert into doc_chunks (source, course_no, module, section_no, section_title, page, "
            "lang, text, context_line, label) values (:source, :course_no, :module, :section_no, "
            ":section_title, :page, :lang, :text, :context_line, :label)"
        ),
        rows,
    )
    return len(rows)


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

    async def search(self, query: str, lang: str, limit: int) -> list[Passage]:
        async with self._engine.connect() as conn:
            return await search_chunks(conn, query, lang, limit)
