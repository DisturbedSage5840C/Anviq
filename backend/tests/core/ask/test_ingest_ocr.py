from functools import partial
from pathlib import Path

import pytest

from app.core.ask import ingest
from app.core.ask.chunking import SourceDoc
from app.core.ask.ingest import IngestError, chunks_for
from app.core.ask.ocr import cache_path, write_cache

HINDI_TEXT = "यह एक वाक्य है। " * 8


def _pdf(raw: Path, name: str = "books/h1/h101.pdf") -> Path:
    path = raw / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-")
    return path


def _no_text_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(path: Path):
        raise AssertionError("the PDF text layer must not be read for Hindi")

    monkeypatch.setattr(ingest, "pdf_pages", fail)


def test_hindi_chunks_come_from_the_ocr_cache_not_the_text_layer(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    pdf = _pdf(raw)
    write_cache(cache_path(raw, pdf), ["", HINDI_TEXT, HINDI_TEXT])
    _no_text_layer(monkeypatch)
    doc = SourceDoc("NCERT", None, "", "hi", book_code="h1", chapter_no=1)

    chunks = chunks_for(pdf, doc, raw_dir=raw)

    assert chunks
    assert {chunk.page for chunk in chunks} <= {2, 3}


def test_hindi_without_a_cache_stops_and_names_the_ocr_script(tmp_path):
    raw = tmp_path / "raw"
    pdf = _pdf(raw)
    doc = SourceDoc("NCERT", None, "", "hi", book_code="h1", chapter_no=1)

    with pytest.raises(IngestError, match=r"scripts\.ocr_corpus"):
        chunks_for(pdf, doc, raw_dir=raw)


def test_english_ignores_the_ocr_cache(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    pdf = _pdf(raw)
    monkeypatch.setattr(ingest, "pdf_pages", lambda path: iter([(1, "plain english text " * 40)]))
    doc = SourceDoc("NCERT", None, "", "en", book_code="e1", chapter_no=1)

    chunks = chunks_for(pdf, doc, raw_dir=raw)

    assert chunks


def test_a_hindi_file_outside_the_download_folder_is_an_ingest_error(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    elsewhere = _pdf(tmp_path / "other")
    doc = SourceDoc("NIPUN", None, "", "hi")

    with pytest.raises(IngestError, match="outside"):
        chunks_for(elsewhere, doc, raw_dir=raw)


def test_without_a_download_folder_the_text_layer_is_still_used(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "pdf_pages", lambda path: iter([(1, HINDI_TEXT)]))
    doc = SourceDoc("NIPUN", None, "", "hi")

    chunks = chunks_for(_pdf(tmp_path), doc)

    assert chunks


def test_the_cache_respects_a_page_range_for_a_combined_book(tmp_path):
    raw = tmp_path / "raw"
    pdf = _pdf(raw, "documents/combined.pdf")
    write_cache(cache_path(raw, pdf), [HINDI_TEXT] * 5)
    doc = SourceDoc("NISHTHA FLN", 2, "Two", "hi", first_page=3, last_page=4)

    chunks = chunks_for(pdf, doc, raw_dir=raw)

    assert {chunk.page for chunk in chunks} <= {3, 4}


def test_a_dry_run_with_the_download_folder_bound_stops_on_a_missing_cache(tmp_path):
    raw = tmp_path / "raw"
    pdf = _pdf(raw)
    doc = SourceDoc("NCERT", None, "", "hi", book_code="h1", chapter_no=1)
    chunker = partial(chunks_for, raw_dir=raw)

    with pytest.raises(IngestError, match=r"scripts\.ocr_corpus"):
        ingest.count_chunks([(pdf, doc)], chunker=chunker)
