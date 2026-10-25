"""Load NISHTHA / NIPUN PDFs into `doc_chunks` (plan section 4.8, ingestion).

The manifest is a CSV with columns: path, source, course_no, course_title, lang, and optionally
first_page and last_page (inclusive PDF pages, for a book that holds several courses; blank means
the whole file). Paths are relative to the manifest. Text is extracted with PyMuPDF, an optional
dependency because only ingestion needs it:

    uv sync --group ingest
    uv run python -m app.core.ask.ingest ../content/corpus/manifest.csv

A Hindi PDF that is scanned, or whose text comes out as broken glyphs, must be OCRed first (plan
4.8 step 2); the script warns when a page yields almost no Devanagari for a Hindi document.
"""

import argparse
import asyncio
import csv
import logging
import re
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.core.ask.chunking import Chunk, SourceDoc, chunk_document
from app.db.corpus import store_chunks

logger = logging.getLogger(__name__)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MIN_DEVANAGARI_SHARE = 0.3


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def read_manifest(path: Path) -> list[tuple[Path, SourceDoc]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        (
            path.parent / row["path"],
            SourceDoc(
                row["source"],
                _optional_int(row.get("course_no")),
                row.get("course_title", ""),
                row["lang"],
                _optional_int(row.get("first_page")),
                _optional_int(row.get("last_page")),
            ),
        )
        for row in rows
    ]


def pdf_pages(path: Path) -> Iterator[tuple[int, str]]:
    import fitz  # type: ignore[import-not-found,import-untyped,unused-ignore]  # PyMuPDF

    with fitz.open(path) as document:
        for number, page in enumerate(document, start=1):
            yield number, page.get_text()


def pages_in_range(pages: list[tuple[int, str]], doc: SourceDoc) -> list[tuple[int, str]]:
    """The pages of one course inside a combined book; every page when the doc names no range."""
    first = doc.first_page if doc.first_page is not None else 0
    last = doc.last_page if doc.last_page is not None else float("inf")
    return [(number, text) for number, text in pages if first <= number <= last]


def looks_broken(text: str, lang: str) -> bool:
    """A Hindi page whose letters are mostly not Devanagari was probably scanned or mis-encoded."""
    letters = [c for c in text if c.isalpha()]
    if lang != "hi" or len(letters) < 50:
        return False
    return sum(bool(_DEVANAGARI.match(c)) for c in letters) / len(letters) < MIN_DEVANAGARI_SHARE


def chunks_for(path: Path, doc: SourceDoc) -> list[Chunk]:
    pages = pages_in_range(list(pdf_pages(path)), doc)
    broken = [n for n, t in pages if looks_broken(t, doc.lang)]
    if broken:
        logger.warning("%s: %d pages look scanned or mis-encoded; OCR them", path.name, len(broken))
    return chunk_document(doc, pages)


async def _main(manifest: Path) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        for path, doc in read_manifest(manifest):
            chunks = chunks_for(path, doc)
            async with engine.begin() as conn:
                written = await store_chunks(conn, chunks, [None] * len(chunks))
            print(f"{path.name}: {written} chunks")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest NISHTHA/NIPUN PDFs into doc_chunks")
    parser.add_argument("manifest", type=Path)
    asyncio.run(_main(parser.parse_args().manifest))


if __name__ == "__main__":
    main()
