"""Split NISHTHA / NIPUN text into section-aware chunks that carry their own citation label.

Plan section 4.8, ingestion steps 2-3. Chunks never cross a section heading, and run 300 to 600
tokens. The citation shown to a teacher is built from this metadata, never from model output, so
a model cannot invent a course or section number.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from typing import NamedTuple

MIN_TOKENS = 300
MAX_TOKENS = 600
# A rough, script-independent token estimate: Devanagari words split into more tokens than English.
TOKENS_PER_WORD = 1.6

# The Hindi NISHTHA PDF extracts "मॉड्यूल" as "मॉĠूल", and chapter dividers double the first letter.
_HINDI_MODULE = r"म{1,2}ॉ(?:ड्य{1,2}|Ġ)ूल"

# "3.2 Title", "3.2.1 Title", "Module 3", "मॉड्यूल 3", "Unit 2", "इकाई 2", "Section 4".
_HEADING = re.compile(
    r"^\s*(?:(?P<num>\d+(?:\.\d+){1,3})\.?\s+(?P<title>\S.{0,120})"
    rf"|(?:module|{_HINDI_MODULE}|unit|इकाई|section|खंड)\s+(?P<mod>\d+)\s*[:.\-–]?\s*(?P<mtitle>.{{0,120}}))\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceDoc:
    source: str  # "NISHTHA FLN" or "NIPUN Bharat"
    course_no: int | None
    course_title: str
    lang: str
    # Inclusive PDF page range, for a combined book that holds several courses; None means the
    # whole file.
    first_page: int | None = None
    last_page: int | None = None
    # Set for an NCERT textbook chapter (one PDF per chapter). Chapter and book come from the
    # file, so a textbook is never split on heading patterns.
    class_level: int | None = None
    subject: str | None = None
    book_code: str | None = None
    book_title: str | None = None
    chapter_no: int | None = None
    chapter_title: str | None = None


@dataclass(frozen=True)
class Chunk:
    source: str
    course_no: int | None
    course_title: str
    module: str | None
    section_no: str | None
    section_title: str | None
    page: int
    lang: str
    text: str
    class_level: int | None = None
    subject: str | None = None
    book_code: str | None = None
    book_title: str | None = None
    chapter_no: int | None = None
    chapter_title: str | None = None

    def label(self) -> str:
        """The citation line, e.g. "NISHTHA FLN Course 9: Foundational Numeracy, Module 3, §3.2"."""
        if self.book_code:
            return self._textbook_label()
        parts = [self.source]
        if self.course_no is not None:
            parts[0] += f" Course {self.course_no}"
            if self.course_title:
                parts[0] += f": {self.course_title}"
        if self.module:
            parts.append(f"Module {self.module}")
        if self.section_no:
            parts.append(f"§{self.section_no}")
        return ", ".join(parts)

    def _textbook_label(self) -> str:
        """A textbook citation, e.g. "NCERT Class 3 Maths Mela, Ch 4: Fun with Shapes, p.12"."""
        book = " ".join(
            part
            for part in (
                self.source,
                f"Class {self.class_level}" if self.class_level else None,
                self.book_title,
            )
            if part
        )
        chapter = None
        if self.chapter_no is not None:
            chapter = f"Ch {self.chapter_no}"
            if self.chapter_title:
                chapter += f": {self.chapter_title}"
        return ", ".join(part for part in (book, chapter, f"p.{self.page}") if part)


def estimate_tokens(text: str) -> int:
    return round(len(text.split()) * TOKENS_PER_WORD)


class _Line(NamedTuple):
    page: int
    text: str


@dataclass(frozen=True)
class _Section:
    module: str | None
    number: str | None
    title: str | None
    page: int
    lines: tuple[_Line, ...]


def _sections(pages: Iterable[tuple[int, str]], *, headings: bool = True) -> Iterator[_Section]:
    current = _Section(None, None, None, 1, ())
    module: str | None = None
    for page_no, page_text in pages:
        if not current.lines:
            current = replace(current, page=page_no)
        for line in page_text.splitlines():
            heading = _HEADING.match(line) if headings else None
            if heading is None:
                if line.strip():
                    current = replace(current, lines=(*current.lines, _Line(page_no, line.strip())))
                continue
            if current.lines:
                yield current
            if heading.group("mod"):
                module = heading.group("mod")
                current = _Section(
                    module, None, heading.group("mtitle").strip() or None, page_no, ()
                )
            else:
                # A module is only known from an explicit "Module N" heading; a section number
                # such as 5.2 is a chapter in some documents (NIPUN Bharat), not a module.
                number = heading.group("num")
                current = _Section(module, number, heading.group("title").strip(), page_no, ())
    if current.lines:
        yield current


def _windows(lines: tuple[_Line, ...]) -> Iterator[tuple[int, str]]:
    """Paragraph-preserving windows of at most MAX_TOKENS, each with the page it starts on.

    A short tail joins the previous window.
    """
    windows: list[list[_Line]] = [[]]
    size = 0
    for line in lines:
        cost = estimate_tokens(line.text)
        if size + cost > MAX_TOKENS and windows[-1]:
            windows.append([])
            size = 0
        windows[-1].append(line)
        size += cost
    if len(windows) > 1 and _tokens(windows[-1]) < MIN_TOKENS // 2:
        tail = windows.pop()
        windows[-1].extend(tail)
    for window in windows:
        if window:
            yield window[0].page, " ".join(line.text for line in window)


def _tokens(window: list[_Line]) -> int:
    return estimate_tokens(" ".join(line.text for line in window))


def chunk_document(doc: SourceDoc, pages: Iterable[tuple[int, str]]) -> list[Chunk]:
    """`pages` are (page number, extracted text) in reading order."""
    return [
        Chunk(
            source=doc.source,
            course_no=doc.course_no,
            course_title=doc.course_title,
            module=section.module,
            section_no=section.number,
            section_title=section.title,
            page=page,
            lang=doc.lang,
            text=text,
            class_level=doc.class_level,
            subject=doc.subject,
            book_code=doc.book_code,
            book_title=doc.book_title,
            chapter_no=doc.chapter_no,
            chapter_title=doc.chapter_title,
        )
        for section in _sections(pages, headings=doc.book_code is None)
        for page, text in _windows(section.lines)
    ]
