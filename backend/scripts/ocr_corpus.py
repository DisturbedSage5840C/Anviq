"""Read the Hindi corpus PDFs with OCR, because their text layer repeats and garbles letters.

Run from the backend folder, on the machine that holds the downloads. It needs `pdftoppm`
(poppler) and `tesseract` with the `hin` and `eng` language data. It skips any file that already
has a cache under raw/ocr/, so an interrupted run is resumed by running it again.

    uv run python -m scripts.ocr_corpus --dry-run   # list what would be read
    uv run python -m scripts.ocr_corpus             # read it (about 10-15 minutes on 8 workers)
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from app.core.ask.ingest import IngestError, corpus_docs
from app.core.ask.ocr import ocr_all, pdfs_needing_ocr
from app.core.ask.sources import SourcesError

CORPUS_DIR = Path(__file__).resolve().parents[2] / "content" / "corpus"
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)
EXIT_FAILED_FILES = 1
EXIT_BAD_INPUT = 2
EXIT_INTERRUPTED = 130


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=CORPUS_DIR / "manifest.csv")
    parser.add_argument("--sources", type=Path, default=CORPUS_DIR / "sources.yaml")
    parser.add_argument("--raw", type=Path, default=CORPUS_DIR / "raw")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="pages read at once")
    parser.add_argument("--dry-run", action="store_true", help="list the files; read nothing")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse(argv)
    if args.workers < 1:
        logging.error("--workers must be at least 1")
        return EXIT_BAD_INPUT
    try:
        docs = corpus_docs(args.manifest, args.sources, args.raw)
        pdfs = pdfs_needing_ocr(docs, args.raw)
    except (IngestError, SourcesError, OSError) as exc:
        logging.error("ocr: %s", exc)
        return EXIT_BAD_INPUT
    logging.info("%d Hindi files still need OCR", len(pdfs))
    if args.dry_run or not pdfs:
        return 0
    started = time.monotonic()

    def report(index: int, total: int, pdf: Path, pages: int) -> None:
        elapsed = time.monotonic() - started
        logging.info("[%d/%d] %s: %d pages (%.0fs elapsed)", index, total, pdf.name, pages, elapsed)

    try:
        summary = ocr_all(pdfs, args.raw, workers=args.workers, on_progress=report)
    except KeyboardInterrupt:
        logging.warning("stopped; run the same command again to resume")
        return EXIT_INTERRUPTED
    logging.info("read %d pages; %d files failed", summary.read, len(summary.failed))
    for pdf, reason in summary.failed:
        logging.warning("failed %s: %s", pdf, reason)
    return EXIT_FAILED_FILES if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
