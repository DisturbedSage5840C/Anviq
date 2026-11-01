"""Load the guidance documents and NCERT textbooks into `doc_chunks` (plan section 4.8).

The manifest is a CSV with columns: path, source, course_no, course_title, lang, and optionally
first_page and last_page (inclusive PDF pages, for a book that holds several courses; blank means
the whole file). Paths are relative to the manifest. With `--sources`, every downloaded NCERT
chapter listed in sources.yaml is added too. Text is extracted with PyMuPDF, an optional
dependency because only ingestion needs it:

    uv sync --group ingest
    uv run python -m app.core.ask.ingest ../content/corpus/manifest.csv --dry-run \
        --sources ../content/corpus/sources.yaml          # chunk and count, touch no database
    uv run python -m app.core.ask.ingest ../content/corpus/manifest.csv \
        --sources ../content/corpus/sources.yaml          # replace each document's rows

Ingesting again replaces a document's rows instead of adding a second copy.

A Hindi PDF that is scanned, or whose text comes out as broken glyphs, must be OCRed first (plan
4.8 step 2); the script warns when a page yields almost no Devanagari for a Hindi document.
"""

import argparse
import asyncio
import csv
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.core.ask.chunking import Chunk, SourceDoc, chunk_document
from app.core.ask.ocr import OcrError, cache_path, read_cache
from app.core.ask.sources import load_sources
from app.core.ask.text_clean import clean_text
from app.core.ask.textbooks import textbook_docs
from app.db.corpus import replace_chunks

logger = logging.getLogger(__name__)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MIN_DEVANAGARI_SHARE = 0.3

DocPair = tuple[Path, SourceDoc]
Chunker = Callable[[Path, SourceDoc], list[Chunk]]


class IngestError(Exception):
    """The corpus cannot be ingested as listed; nothing was written."""


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def _optional_text(value: str | None) -> str | None:
    return value or None


def _source_doc(row: dict[str, str]) -> SourceDoc:
    return SourceDoc(
        row["source"],
        _optional_int(row.get("course_no")),
        row.get("course_title", ""),
        row["lang"],
        _optional_int(row.get("first_page")),
        _optional_int(row.get("last_page")),
        class_level=_optional_int(row.get("class_level")),
        subject=_optional_text(row.get("subject")),
        book_code=_optional_text(row.get("book_code")),
        book_title=_optional_text(row.get("book_title")),
        chapter_no=_optional_int(row.get("chapter_no")),
        chapter_title=_optional_text(row.get("chapter_title")),
    )


def read_manifest(path: Path) -> list[tuple[Path, SourceDoc]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [(path.parent / row["path"], _source_doc(row)) for row in rows]


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


def _source_pages(path: Path, doc: SourceDoc, raw_dir: Path | None) -> list[tuple[int, str]]:
    """The pages to chunk. Hindi PDFs have a corrupt text layer, so with a download folder their
    pages come from the OCR cache; a missing cache stops the run rather than ingest bad text."""
    if raw_dir is None or doc.lang != "hi":
        return list(pdf_pages(path))
    try:
        cached = cache_path(raw_dir, path)
    except OcrError as exc:
        raise IngestError(str(exc)) from exc
    if not cached.is_file():
        raise IngestError(f"{path.name}: no OCR text yet; run `python -m scripts.ocr_corpus` first")
    return read_cache(cached)


def chunks_for(path: Path, doc: SourceDoc, raw_dir: Path | None = None) -> list[Chunk]:
    pages = [(n, clean_text(t)) for n, t in pages_in_range(_source_pages(path, doc, raw_dir), doc)]
    broken = [n for n, t in pages if looks_broken(t, doc.lang)]
    if broken:
        logger.warning("%s: %d pages look scanned or mis-encoded; OCR them", path.name, len(broken))
    return chunk_document(doc, pages)


def corpus_docs(manifest: Path, sources: Path | None, raw_dir: Path) -> list[DocPair]:
    """The manifest's documents, then every downloaded chapter of the books in `sources`."""
    docs = read_manifest(manifest)
    if sources is not None:
        docs += textbook_docs(load_sources(sources), raw_dir)
    return docs


def missing_files(docs: Sequence[DocPair]) -> list[Path]:
    return [path for path, _ in docs if not path.is_file()]


def _chunk_all(docs: Sequence[DocPair], chunker: Chunker) -> list[tuple[str, list[Chunk]]]:
    """Chunk every document before any write, so a bad file stops the run with nothing changed."""
    absent = missing_files(docs)
    if absent:
        raise IngestError("missing files: " + ", ".join(str(p) for p in absent))
    chunked: list[tuple[str, list[Chunk]]] = []
    for path, doc in docs:
        chunks = chunker(path, doc)
        if not chunks:
            raise IngestError(f"{path.name}: no chunks were produced; is it scanned or empty?")
        chunked.append((path.name, chunks))
    return chunked


def count_chunks(docs: Sequence[DocPair], chunker: Chunker = chunks_for) -> dict[str, int]:
    """A dry run: how many chunks each file gives, without touching the database."""
    counts: dict[str, int] = {}
    for name, chunks in _chunk_all(docs, chunker):
        counts[name] = counts.get(name, 0) + len(chunks)
    return counts


async def ingest_docs(
    engine: AsyncEngine, docs: Sequence[DocPair], chunker: Chunker = chunks_for
) -> dict[str, int]:
    """Replace each document's rows, one transaction per document. Counts are per file name, so
    the courses of one NISHTHA file add up."""
    chunked = _chunk_all(docs, chunker)
    written: dict[str, int] = {}
    for name, chunks in chunked:
        async with engine.begin() as conn:
            stored = await replace_chunks(conn, chunks, [None] * len(chunks))
        written[name] = written.get(name, 0) + stored
    return written


async def _main(manifest: Path, sources: Path | None, raw_dir: Path, dry_run: bool) -> None:
    docs = corpus_docs(manifest, sources, raw_dir)
    chunker = partial(chunks_for, raw_dir=raw_dir)
    if dry_run:
        counts = count_chunks(docs, chunker)
    else:
        engine = create_async_engine(get_settings().database_url)
        try:
            counts = await ingest_docs(engine, docs, chunker)
        finally:
            await engine.dispose()
    for name, count in counts.items():
        print(f"{name}: {count} chunks")
    print(f"{len(counts)} files, {sum(counts.values())} chunks" + (" (dry run)" if dry_run else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest guidance PDFs and NCERT books")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--sources", type=Path, help="sources.yaml: also ingest the NCERT books")
    parser.add_argument("--raw", type=Path, help="download folder (default: raw/ by the manifest)")
    parser.add_argument("--dry-run", action="store_true", help="chunk and count; no database")
    args = parser.parse_args()
    raw_dir = args.raw or args.manifest.parent / "raw"
    try:
        asyncio.run(_main(args.manifest, args.sources, raw_dir, args.dry_run))
    except IngestError as exc:
        raise SystemExit(f"ingest: {exc}") from exc


if __name__ == "__main__":
    main()
