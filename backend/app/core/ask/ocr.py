"""OCR for the Hindi PDFs whose text layer cannot be trusted.

The Hindi NCERT textbooks and the Hindi NISHTHA book carry a text layer that repeats glyphs
('उससके पासस', 'किततनी'), mixes in stray Latin letters and sometimes U+FFFD. A repeated letter can be
a real double letter in Hindi, so no rule can undo it. The page images are fine, so we read
those with Tesseract instead and keep the result in a cache next to the downloads:

    raw/books/chmm1/chmm101.pdf  ->  raw/ocr/books/chmm1/chmm101.txt   (pages split by form feed)

Both programs (pdftoppm from poppler, tesseract) run only on the machine that builds the corpus.
They are started with an argument list, never through a shell, and the PDF is only ever an argument.
"""

import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.core.ask.chunking import SourceDoc

logger = logging.getLogger(__name__)

OCR_DIR = "ocr"
PAGE_BREAK = "\f"
DEFAULT_LANGUAGES = "hin+eng"
DEFAULT_DPI = 200
COMMAND_TIMEOUT_SECONDS = 600

CommandRunner = Callable[[Sequence[str]], str]


class OcrError(RuntimeError):
    """A PDF could not be read by OCR, or the OCR tools are missing."""


def run_command(args: Sequence[str]) -> str:
    """Run one program and return its standard output; any failure becomes an `OcrError`."""
    # One thread per Tesseract process: we parallelise across pages instead.
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    try:
        done = subprocess.run(  # noqa: S603 - fixed program names, no shell, paths as arguments
            list(args),
            capture_output=True,
            text=True,
            check=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            env=env,
        )
    except FileNotFoundError as exc:
        raise OcrError(f"{args[0]} is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"{args[0]} timed out after {COMMAND_TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()[:300]
        raise OcrError(f"{args[0]} failed (exit {exc.returncode}): {detail}") from exc
    return done.stdout


def cache_path(raw_dir: Path, pdf: Path) -> Path:
    """Where the OCR text of `pdf` is kept; `pdf` must sit inside the download folder."""
    try:
        relative = pdf.relative_to(raw_dir)
    except ValueError as exc:
        raise OcrError(f"{pdf} is outside the download folder {raw_dir}") from exc
    return raw_dir / OCR_DIR / relative.with_suffix(".txt")


def write_cache(target: Path, pages: Sequence[str]) -> None:
    """Save the pages in one step, so an interrupted run never leaves a half-written cache."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.write_text(PAGE_BREAK.join(pages), encoding="utf-8")
    temporary.replace(target)


def read_cache(source: Path) -> list[tuple[int, str]]:
    """The cached pages as (page number, text), numbered from 1."""
    text = source.read_text(encoding="utf-8")
    return list(enumerate(text.split(PAGE_BREAK), start=1))


def ocr_pdf(
    pdf: Path,
    *,
    runner: CommandRunner = run_command,
    languages: str = DEFAULT_LANGUAGES,
    dpi: int = DEFAULT_DPI,
    workers: int = 1,
) -> list[str]:
    """OCR every page of `pdf`. The result has one text per page, in page order."""
    with tempfile.TemporaryDirectory(prefix="anviq-ocr-") as scratch:
        prefix = Path(scratch) / "page"
        runner(["pdftoppm", "-r", str(dpi), "-gray", "-png", str(pdf), str(prefix)])
        images = sorted(Path(scratch).glob("page-*.png"))
        if not images:
            raise OcrError(f"{pdf.name}: no pages were rendered")

        def recognise(image: Path) -> str:
            text = runner(["tesseract", str(image), "stdout", "-l", languages, "--psm", "3"])
            return text.replace(PAGE_BREAK, "").strip()

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return list(pool.map(recognise, images))


def ensure_cached(
    pdf: Path,
    raw_dir: Path,
    *,
    runner: CommandRunner = run_command,
    languages: str = DEFAULT_LANGUAGES,
    workers: int = 1,
) -> int:
    """OCR `pdf` unless its cache exists. Returns the number of pages read now (0 if cached)."""
    target = cache_path(raw_dir, pdf)
    if target.is_file():
        return 0
    pages = ocr_pdf(pdf, runner=runner, languages=languages, workers=workers)
    write_cache(target, pages)
    logger.info("%s: %d pages read by OCR", pdf.name, len(pages))
    return len(pages)


def pdfs_needing_ocr(docs: Sequence[tuple[Path, SourceDoc]], raw_dir: Path) -> list[Path]:
    """Each Hindi PDF that has no OCR cache yet, once, in the order the corpus lists them."""
    wanted: dict[Path, None] = {}
    for pdf, doc in docs:
        if doc.lang == "hi" and not cache_path(raw_dir, pdf).is_file():
            wanted[pdf] = None
    return list(wanted)


@dataclass(frozen=True)
class OcrSummary:
    read: int  # pages read by OCR in this run
    failed: tuple[tuple[Path, str], ...]  # files that could not be read, with the reason


ProgressCallback = Callable[[int, int, Path, int], None]  # index, total, pdf, pages read


def ocr_all(
    pdfs: Sequence[Path],
    raw_dir: Path,
    *,
    runner: CommandRunner = run_command,
    languages: str = DEFAULT_LANGUAGES,
    workers: int = 1,
    on_progress: ProgressCallback | None = None,
) -> OcrSummary:
    """OCR each file in turn. A file that fails is reported and skipped; the rest still run."""
    read = 0
    failed: list[tuple[Path, str]] = []
    for index, pdf in enumerate(pdfs, start=1):
        try:
            pages = ensure_cached(pdf, raw_dir, runner=runner, languages=languages, workers=workers)
        except OcrError as exc:
            logger.warning("%s: %s", pdf.name, exc)
            failed.append((pdf, str(exc)))
            pages = 0
        read += pages
        if on_progress is not None:
            on_progress(index, len(pdfs), pdf, pages)
    return OcrSummary(read=read, failed=tuple(failed))
