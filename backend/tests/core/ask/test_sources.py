from pathlib import Path

import pytest

from app.core.ask.sources import (
    BASE_URL,
    Book,
    SourcesError,
    book_files,
    load_sources,
    plan_downloads,
)

REPO_SOURCES = Path(__file__).parents[4] / "content" / "corpus" / "sources.yaml"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


GOOD = """
books:
  - {code: aejm1, class_level: 1, subject: mathematics, lang: en, title: "Joyful Mathematics", chapters: 3}
documents:
  - {key: nipun, title: "NIPUN", url: "https://example.org/nipun.pdf"}
"""


def test_book_files_lists_prelims_then_padded_chapters():
    book = Book("aejm1", 1, "mathematics", "en", "Joyful Mathematics", 3)

    assert book_files(book) == ("aejm1ps.pdf", "aejm101.pdf", "aejm102.pdf", "aejm103.pdf")


def test_plan_downloads_builds_ncert_urls_and_safe_relative_paths(tmp_path):
    sources = load_sources(_write(tmp_path, GOOD))

    items = plan_downloads(sources)

    assert items[0].url == f"{BASE_URL}/aejm1ps.pdf"
    assert items[0].relpath == "books/aejm1/aejm1ps.pdf"
    assert items[-1].relpath == "documents/nipun.pdf"
    assert len(items) == 5


def test_plan_downloads_can_be_narrowed_by_class_and_language(tmp_path):
    body = GOOD.replace(
        "documents:",
        '  - {code: bhsr1, class_level: 2, subject: hindi, lang: hi, title: "Sarangi", chapters: 1}\n'
        "documents:",
    )
    sources = load_sources(_write(tmp_path, body))

    items = plan_downloads(sources, class_level=2, lang="hi", include_documents=False)

    assert [i.relpath for i in items] == ["books/bhsr1/bhsr1ps.pdf", "books/bhsr1/bhsr101.pdf"]


@pytest.mark.parametrize(
    "bad",
    [
        GOOD.replace("class_level: 1", "class_level: 6"),
        GOOD.replace("lang: en", "lang: fr"),
        GOOD.replace("aejm1", "../x"),
        GOOD.replace("chapters: 3", "chapters: 0"),
        GOOD.replace("chapters: 3", "chapters: 120"),
        GOOD.replace("nipun,", "../nipun,"),
        GOOD.replace("https://example.org/nipun.pdf", "ftp://example.org/nipun.pdf"),
    ],
)
def test_load_sources_rejects_invalid_entries(tmp_path, bad):
    with pytest.raises(SourcesError):
        load_sources(_write(tmp_path, bad))


def test_load_sources_rejects_duplicate_codes(tmp_path):
    line = GOOD.splitlines()[2]
    with pytest.raises(SourcesError, match="duplicate"):
        load_sources(_write(tmp_path, GOOD.replace(line, f"{line}\n{line}")))


def test_load_sources_rejects_a_missing_file(tmp_path):
    with pytest.raises(SourcesError, match="cannot read"):
        load_sources(tmp_path / "nope.yaml")


def test_the_shipped_sources_file_is_valid_and_covers_classes_1_to_5():
    sources = load_sources(REPO_SOURCES)

    assert len(sources.books) == 26
    assert {b.class_level for b in sources.books} == {1, 2, 3, 4, 5}
    assert sum(b.chapters for b in sources.books) == 342
