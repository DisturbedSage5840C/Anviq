"""Turn the downloaded NCERT chapter PDFs into `(path, SourceDoc)` pairs ready for chunking.

`sources.yaml` says which books exist and how many chapters each has. The download folder holds
`books/{code}/{code}NN.pdf` for each chapter that was fetched. Preliminary pages (`{code}ps.pdf`)
are skipped: they hold the title page and the contents list, not teaching text.
"""

from pathlib import Path

from app.core.ask.chunking import SourceDoc
from app.core.ask.sources import Book, Sources, book_files

SOURCE_NAME = "NCERT"
_PRELIM_SUFFIX = "ps.pdf"


def _chapter_docs(book: Book, raw_dir: Path) -> list[tuple[Path, SourceDoc]]:
    docs: list[tuple[Path, SourceDoc]] = []
    for number, name in enumerate(book_files(book)[1:], start=1):
        path = raw_dir / "books" / book.code / name
        if not path.is_file():
            continue
        docs.append(
            (
                path,
                SourceDoc(
                    SOURCE_NAME,
                    None,
                    "",
                    book.lang,
                    class_level=book.class_level,
                    subject=book.subject,
                    book_code=book.code,
                    book_title=book.title,
                    chapter_no=number,
                ),
            )
        )
    return docs


def textbook_docs(
    sources: Sources,
    raw_dir: Path,
    *,
    class_level: int | None = None,
    lang: str | None = None,
) -> list[tuple[Path, SourceDoc]]:
    """Every downloaded chapter, optionally narrowed to one class or language."""
    docs: list[tuple[Path, SourceDoc]] = []
    for book in sources.books:
        if class_level not in (None, book.class_level) or lang not in (None, book.lang):
            continue
        docs.extend(_chapter_docs(book, raw_dir))
    return docs


def missing_chapters(sources: Sources, raw_dir: Path) -> list[str]:
    """Chapter files named by sources.yaml that the download did not deliver."""
    missing: list[str] = []
    for book in sources.books:
        for name in book_files(book):
            if name.endswith(_PRELIM_SUFFIX):
                continue
            relpath = f"books/{book.code}/{name}"
            if not (raw_dir / relpath).is_file():
                missing.append(relpath)
    return missing
