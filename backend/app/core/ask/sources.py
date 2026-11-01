"""The list of NCERT books and guidance documents to fetch, and the files each one is made of.

`content/corpus/sources.yaml` names each Class 1-5 book by its NCERT code. The code is also the
file prefix: `{code}ps.pdf` is the preliminary pages and `{code}01.pdf` onward are the chapters.
Everything read from the file is checked here, because the values end up in URLs and file paths.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

BASE_URL = "https://ncert.nic.in/textbook/pdf"
CLASS_LEVELS = frozenset({1, 2, 3, 4, 5})
LANGS = frozenset({"hi", "en"})
MAX_CHAPTERS = 99  # NCERT numbers chapters with two digits
_CODE = re.compile(r"[a-z0-9]{3,12}")
_KEY = re.compile(r"[a-z0-9_]{2,40}")
_URL_SCHEMES = frozenset({"http", "https"})


class SourcesError(Exception):
    """The sources file is missing or has an invalid entry."""


@dataclass(frozen=True)
class Book:
    code: str
    class_level: int
    subject: str
    lang: str
    title: str
    chapters: int


@dataclass(frozen=True)
class Document:
    key: str
    title: str
    url: str


@dataclass(frozen=True)
class Sources:
    books: tuple[Book, ...]
    documents: tuple[Document, ...]


@dataclass(frozen=True)
class DownloadItem:
    url: str
    relpath: str  # relative to the download folder, e.g. books/aejm1/aejm1ps.pdf


def _book(entry: object) -> Book:
    if not isinstance(entry, dict):
        raise SourcesError(f"book entry is not a mapping: {entry!r}")
    try:
        book = Book(
            code=str(entry["code"]),
            class_level=int(entry["class_level"]),
            subject=str(entry["subject"]),
            lang=str(entry["lang"]),
            title=str(entry["title"]),
            chapters=int(entry["chapters"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SourcesError(f"bad book entry {entry!r}: {exc}") from exc
    if not _CODE.fullmatch(book.code):
        raise SourcesError(f"bad book code {book.code!r}")
    if book.class_level not in CLASS_LEVELS:
        raise SourcesError(f"{book.code}: class_level must be 1 to 5")
    if book.lang not in LANGS:
        raise SourcesError(f"{book.code}: lang must be hi or en")
    if not 1 <= book.chapters <= MAX_CHAPTERS:
        raise SourcesError(f"{book.code}: chapters must be 1 to {MAX_CHAPTERS}")
    return book


def _document(entry: object) -> Document:
    if not isinstance(entry, dict):
        raise SourcesError(f"document entry is not a mapping: {entry!r}")
    try:
        doc = Document(str(entry["key"]), str(entry["title"]), str(entry["url"]))
    except KeyError as exc:
        raise SourcesError(f"bad document entry {entry!r}: missing {exc}") from exc
    if not _KEY.fullmatch(doc.key):
        raise SourcesError(f"bad document key {doc.key!r}")
    parsed = urlparse(doc.url)
    if parsed.scheme not in _URL_SCHEMES or not parsed.netloc:
        raise SourcesError(f"{doc.key}: url must be http or https")
    return doc


def _reject_duplicates(names: list[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise SourcesError(f"duplicate {what} {name!r}")
        seen.add(name)


def load_sources(path: Path) -> Sources:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourcesError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SourcesError(f"{path} must hold a mapping with books and documents")
    books = tuple(_book(e) for e in raw.get("books") or ())
    documents = tuple(_document(e) for e in raw.get("documents") or ())
    _reject_duplicates([b.code for b in books], "book code")
    _reject_duplicates([d.key for d in documents], "document key")
    return Sources(books, documents)


def book_files(book: Book) -> tuple[str, ...]:
    """File names of one book: the preliminary pages, then each chapter."""
    chapters = tuple(f"{book.code}{n:02d}.pdf" for n in range(1, book.chapters + 1))
    return (f"{book.code}ps.pdf", *chapters)


def plan_downloads(
    sources: Sources,
    *,
    class_level: int | None = None,
    lang: str | None = None,
    include_documents: bool = True,
) -> tuple[DownloadItem, ...]:
    """Every file to fetch, optionally narrowed to one class or language."""
    items = [
        DownloadItem(f"{BASE_URL}/{name}", f"books/{book.code}/{name}")
        for book in sources.books
        if class_level in (None, book.class_level) and lang in (None, book.lang)
        for name in book_files(book)
    ]
    if include_documents:
        items += [DownloadItem(d.url, f"documents/{d.key}.pdf") for d in sources.documents]
    return tuple(items)
