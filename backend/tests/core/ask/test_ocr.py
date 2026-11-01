from pathlib import Path

import pytest

from app.core.ask.chunking import SourceDoc
from app.core.ask.ocr import (
    OcrError,
    cache_path,
    ensure_cached,
    ocr_all,
    ocr_pdf,
    pdfs_needing_ocr,
    read_cache,
    run_command,
    write_cache,
)


def test_cache_path_mirrors_the_pdf_location_under_an_ocr_folder(tmp_path):
    pdf = tmp_path / "books" / "chmm1" / "chmm101.pdf"

    assert cache_path(tmp_path, pdf) == tmp_path / "ocr" / "books" / "chmm1" / "chmm101.txt"


def test_cache_path_refuses_a_pdf_outside_the_download_folder(tmp_path):
    with pytest.raises(OcrError, match="outside"):
        cache_path(tmp_path / "raw", tmp_path / "elsewhere" / "a.pdf")


def test_a_cache_round_trips_its_pages_in_order(tmp_path):
    target = tmp_path / "ocr" / "a.txt"

    write_cache(target, ["first page", "", "third page"])

    assert read_cache(target) == [(1, "first page"), (2, ""), (3, "third page")]


def test_writing_a_cache_leaves_no_partial_file_behind(tmp_path):
    target = tmp_path / "ocr" / "a.txt"

    write_cache(target, ["one"])

    assert [p.name for p in target.parent.iterdir()] == ["a.txt"]


class FakeTools:
    """Stands in for pdftoppm and tesseract: renders N pages, reads each back as its own name."""

    def __init__(self, pages: int) -> None:
        self.pages = pages
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(list(args))
        if args[0] == "pdftoppm":
            prefix = Path(args[-1])
            for number in range(1, self.pages + 1):
                Path(f"{prefix}-{number:02d}.png").write_bytes(b"png")
            return ""
        image = Path(args[1])
        return f"text of {image.stem}\n\f"


def test_ocr_pdf_returns_one_text_per_page_in_page_order(tmp_path):
    tools = FakeTools(pages=12)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-")

    pages = ocr_pdf(pdf, runner=tools, workers=4)

    assert pages == [f"text of page-{n:02d}" for n in range(1, 13)]


def test_ocr_pdf_passes_the_pdf_and_languages_as_plain_arguments(tmp_path):
    tools = FakeTools(pages=1)
    pdf = tmp_path / "a b.pdf"
    pdf.write_bytes(b"%PDF-")

    ocr_pdf(pdf, runner=tools, languages="hin+eng")

    render, recognise = tools.calls
    assert render[0] == "pdftoppm" and str(pdf) in render
    assert recognise[:1] == ["tesseract"]
    assert recognise[recognise.index("-l") + 1] == "hin+eng"


def test_ocr_pdf_fails_when_no_page_was_rendered(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-")

    with pytest.raises(OcrError, match="no pages"):
        ocr_pdf(pdf, runner=FakeTools(pages=0))


def test_run_command_reports_a_missing_program_by_name():
    with pytest.raises(OcrError, match="not-a-real-program"):
        run_command(["not-a-real-program-xyz"])


def test_run_command_reports_a_failing_program_with_its_message():
    with pytest.raises(OcrError, match="exit"):
        run_command(["python3", "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])


def _pdf(raw: Path, name: str) -> Path:
    path = raw / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-")
    return path


def test_ensure_cached_reads_the_pdf_once_and_saves_the_pages(tmp_path):
    pdf = _pdf(tmp_path, "books/h1/h101.pdf")
    tools = FakeTools(pages=2)

    first = ensure_cached(pdf, tmp_path, runner=tools)
    second = ensure_cached(pdf, tmp_path, runner=tools)

    assert (first, second) == (2, 0)
    assert read_cache(cache_path(tmp_path, pdf)) == [(1, "text of page-01"), (2, "text of page-02")]
    assert len(tools.calls) == 3  # one render and two pages, nothing on the second call


def test_pdfs_needing_ocr_lists_each_uncached_hindi_file_once(tmp_path):
    shared = _pdf(tmp_path, "documents/nishtha_hi.pdf")
    chapter = _pdf(tmp_path, "books/h1/h101.pdf")
    done = _pdf(tmp_path, "books/h1/h102.pdf")
    english = _pdf(tmp_path, "books/e1/e101.pdf")
    write_cache(cache_path(tmp_path, done), ["already read"])
    docs = [
        (shared, SourceDoc("NISHTHA FLN", 1, "One", "hi")),
        (shared, SourceDoc("NISHTHA FLN", 2, "Two", "hi")),
        (chapter, SourceDoc("NCERT", None, "", "hi")),
        (done, SourceDoc("NCERT", None, "", "hi")),
        (english, SourceDoc("NCERT", None, "", "en")),
    ]

    assert pdfs_needing_ocr(docs, tmp_path) == [shared, chapter]


def test_ocr_all_reports_progress_and_keeps_going_after_a_failure(tmp_path):
    good = _pdf(tmp_path, "books/h1/h101.pdf")
    bad = _pdf(tmp_path, "books/h1/h102.pdf")
    tools = FakeTools(pages=1)

    def runner(args: list[str]) -> str:
        if str(bad) in args:
            raise OcrError("pdftoppm failed (exit 1): damaged")
        return tools(args)

    seen: list[tuple[int, int, str]] = []
    summary = ocr_all(
        [bad, good],
        tmp_path,
        runner=runner,
        on_progress=lambda index, total, pdf, pages: seen.append((index, total, pdf.name)),
    )

    assert summary.read == 1
    assert [(p.name, "damaged" in why) for p, why in summary.failed] == [("h102.pdf", True)]
    assert seen == [(1, 2, "h102.pdf"), (2, 2, "h101.pdf")]
    assert cache_path(tmp_path, good).is_file()
    assert not cache_path(tmp_path, bad).exists()
