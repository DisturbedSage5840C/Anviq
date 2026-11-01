from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.core.ask import ingest
from app.core.ask.chunking import Chunk, SourceDoc
from app.core.ask.ingest import IngestError, corpus_docs, ingest_docs, missing_files

MANIFEST = "path,source,course_no,course_title,lang\nraw/documents/a.pdf,NIPUN Bharat,,,en\n"
SOURCES = (
    "books:\n"
    "  - {code: abc1, class_level: 1, subject: mathematics, lang: en, title: T, chapters: 2}\n"
)


def _corpus(tmp_path: Path, *, with_sources: bool = True) -> tuple[Path, Path | None, Path]:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(MANIFEST, encoding="utf-8")
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES, encoding="utf-8")
    raw = tmp_path / "raw"
    (raw / "books" / "abc1").mkdir(parents=True)
    for name in ("abc101.pdf", "abc102.pdf"):
        (raw / "books" / "abc1" / name).write_bytes(b"%PDF-")
    return manifest, (sources if with_sources else None), raw


def test_corpus_docs_lists_manifest_documents_then_textbook_chapters(tmp_path):
    manifest, sources, raw = _corpus(tmp_path)

    docs = corpus_docs(manifest, sources, raw)

    assert [doc.source for _, doc in docs] == ["NIPUN Bharat", "NCERT", "NCERT"]
    assert docs[0][0] == tmp_path / "raw" / "documents" / "a.pdf"
    assert [doc.chapter_no for _, doc in docs[1:]] == [1, 2]


def test_corpus_docs_without_sources_lists_the_manifest_only(tmp_path):
    manifest, _, raw = _corpus(tmp_path, with_sources=False)

    docs = corpus_docs(manifest, None, raw)

    assert [doc.source for _, doc in docs] == ["NIPUN Bharat"]


def test_missing_files_names_each_absent_path(tmp_path):
    manifest, sources, raw = _corpus(tmp_path)

    absent = missing_files(corpus_docs(manifest, sources, raw))

    assert absent == [tmp_path / "raw" / "documents" / "a.pdf"]


class _Conn:
    pass


class _Engine:
    def __init__(self) -> None:
        self.transactions = 0

    @asynccontextmanager
    async def begin(self):
        self.transactions += 1
        yield _Conn()


def _chunk(source: str) -> Chunk:
    return Chunk(source, None, "", None, None, None, 1, "en", "t")


def _present(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"%PDF-")
    return path


async def test_ingest_docs_replaces_each_document_in_its_own_transaction(monkeypatch, tmp_path):
    calls: list[tuple[str, int]] = []

    async def fake_replace(conn, chunks, context_lines):
        assert isinstance(conn, _Conn)
        assert len(context_lines) == len(chunks)
        calls.append((chunks[0].source, len(chunks)))
        return len(chunks)

    monkeypatch.setattr(ingest, "replace_chunks", fake_replace)
    docs = [
        (_present(tmp_path, "a.pdf"), SourceDoc("A", None, "", "en")),
        (_present(tmp_path, "b.pdf"), SourceDoc("B", None, "", "en")),
    ]
    engine = _Engine()

    written = await ingest_docs(
        engine, docs, chunker=lambda path, doc: [_chunk(doc.source), _chunk(doc.source)]
    )

    assert calls == [("A", 2), ("B", 2)]
    assert engine.transactions == 2
    assert written == {"a.pdf": 2, "b.pdf": 2}


async def test_ingest_docs_stops_before_the_database_when_a_file_is_missing(tmp_path):
    docs = [(tmp_path / "gone.pdf", SourceDoc("A", None, "", "en"))]
    engine = _Engine()

    with pytest.raises(IngestError, match="gone.pdf"):
        await ingest_docs(engine, docs, chunker=lambda path, doc: [_chunk("A")])

    assert engine.transactions == 0


async def test_ingest_docs_refuses_a_document_that_yields_no_chunks(tmp_path):
    docs = [(_present(tmp_path, "blank.pdf"), SourceDoc("A", None, "", "en"))]
    engine = _Engine()

    with pytest.raises(IngestError, match="blank.pdf"):
        await ingest_docs(engine, docs, chunker=lambda p, d: [])

    assert engine.transactions == 0


async def test_ingest_docs_adds_up_the_courses_that_share_one_file(monkeypatch, tmp_path):
    async def fake_replace(conn, chunks, context_lines):
        return len(chunks)

    monkeypatch.setattr(ingest, "replace_chunks", fake_replace)
    shared = _present(tmp_path, "nishtha.pdf")
    docs = [
        (shared, SourceDoc("N", 1, "One", "en")),
        (shared, SourceDoc("N", 2, "Two", "en")),
    ]

    written = await ingest_docs(
        _Engine(), docs, chunker=lambda path, doc: [_chunk(doc.source)] * (doc.course_no or 0)
    )

    assert written == {"nishtha.pdf": 3}


def test_count_chunks_adds_up_the_courses_that_share_one_file(tmp_path):
    shared = _present(tmp_path, "nishtha.pdf")
    docs = [
        (shared, SourceDoc("N", 1, "One", "en")),
        (shared, SourceDoc("N", 2, "Two", "en")),
    ]

    counts = ingest.count_chunks(docs, chunker=lambda p, d: [_chunk("N")] * (d.course_no or 0))

    assert counts == {"nishtha.pdf": 3}
