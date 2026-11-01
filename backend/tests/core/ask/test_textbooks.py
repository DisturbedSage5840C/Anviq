from pathlib import Path

from app.core.ask.ingest import read_manifest
from app.core.ask.sources import Book, Document, Sources
from app.core.ask.textbooks import missing_chapters, textbook_docs

MATHS = Book("cemm1", 3, "mathematics", "en", "Maths Mela", 3)
HINDI = Book("dhsr1", 4, "hindi", "hi", "Sarangi", 2)
SOURCES = Sources((MATHS, HINDI), (Document("k", "T", "https://x/y.pdf"),))


def _touch(raw: Path, relpath: str) -> None:
    target = raw / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.7")


def test_each_downloaded_chapter_becomes_a_source_doc_with_its_book_metadata(tmp_path):
    _touch(tmp_path, "books/cemm1/cemm101.pdf")
    _touch(tmp_path, "books/cemm1/cemm103.pdf")

    docs = textbook_docs(SOURCES, tmp_path)

    assert [path.name for path, _ in docs] == ["cemm101.pdf", "cemm103.pdf"]
    first = docs[0][1]
    assert (first.source, first.lang, first.class_level, first.subject) == (
        "NCERT",
        "en",
        3,
        "mathematics",
    )
    assert (first.book_code, first.book_title, first.chapter_no) == ("cemm1", "Maths Mela", 1)
    assert docs[1][1].chapter_no == 3


def test_preliminary_pages_are_not_ingested(tmp_path):
    _touch(tmp_path, "books/cemm1/cemm1ps.pdf")

    assert textbook_docs(SOURCES, tmp_path) == []


def test_a_book_that_was_not_downloaded_yields_nothing(tmp_path):
    assert textbook_docs(SOURCES, tmp_path) == []


def test_docs_can_be_narrowed_to_one_class_and_language(tmp_path):
    _touch(tmp_path, "books/cemm1/cemm101.pdf")
    _touch(tmp_path, "books/dhsr1/dhsr101.pdf")

    docs = textbook_docs(SOURCES, tmp_path, class_level=4, lang="hi")

    assert [doc.book_code for _, doc in docs] == ["dhsr1"]


def test_missing_chapters_lists_what_the_download_did_not_deliver(tmp_path):
    _touch(tmp_path, "books/cemm1/cemm101.pdf")

    missing = missing_chapters(SOURCES, tmp_path)

    assert missing[:2] == ["books/cemm1/cemm102.pdf", "books/cemm1/cemm103.pdf"]
    assert "books/dhsr1/dhsr101.pdf" in missing
    assert all("ps.pdf" not in name for name in missing)


def test_manifest_rows_may_carry_textbook_columns(tmp_path):
    manifest = tmp_path / "m.csv"
    manifest.write_text(
        "path,source,course_no,course_title,lang,class_level,subject,book_code,book_title,"
        "chapter_no,chapter_title\n"
        "a.pdf,NCERT,,,en,3,mathematics,cemm1,Maths Mela,4,Shapes\n",
        encoding="utf-8",
    )

    ((path, doc),) = read_manifest(manifest)

    assert path == tmp_path / "a.pdf"
    assert (doc.class_level, doc.subject, doc.book_code, doc.chapter_no) == (
        3,
        "mathematics",
        "cemm1",
        4,
    )
    assert (doc.book_title, doc.chapter_title) == ("Maths Mela", "Shapes")


def test_manifest_rows_without_textbook_columns_still_load(tmp_path):
    manifest = tmp_path / "m.csv"
    manifest.write_text(
        "path,source,course_no,course_title,lang\nb.pdf,NIPUN Bharat,,,en\n", encoding="utf-8"
    )

    ((_, doc),) = read_manifest(manifest)

    assert doc.book_code is None
    assert doc.class_level is None
