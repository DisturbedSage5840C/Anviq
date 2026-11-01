"""Download the NCERT Class 1-5 books and guidance documents listed in content/corpus/sources.yaml.

Run from the backend folder. By default this only lists what it would fetch (a dry run). Pass
--download to fetch. Files go to content/corpus/raw/, which is git-ignored: the NCERT books carry
a notice that they may not be hosted online or used in software, so the PDFs stay on this machine.

    uv run python -m scripts.fetch_corpus                       # list the plan
    uv run python -m scripts.fetch_corpus --download --class 1  # fetch Class 1 only
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from app.core.ask.fetch import DEFAULT_DELAY, HttpxFetcher, download_all
from app.core.ask.sources import SourcesError, load_sources, plan_downloads

CORPUS_DIR = Path(__file__).resolve().parents[2] / "content" / "corpus"


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, default=CORPUS_DIR / "sources.yaml")
    parser.add_argument("--dest", type=Path, default=CORPUS_DIR / "raw")
    parser.add_argument("--log", type=Path, default=CORPUS_DIR / "fetch_log.csv")
    parser.add_argument("--class", dest="class_level", type=int, choices=range(1, 6))
    parser.add_argument("--lang", choices=("hi", "en"))
    parser.add_argument("--no-documents", action="store_true", help="books only")
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, help="seconds between requests"
    )
    parser.add_argument("--download", action="store_true", help="fetch; without it, only list")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse(argv)
    try:
        sources = load_sources(args.sources)
    except SourcesError as exc:
        logging.error("sources: %s", exc)
        return 2
    items = plan_downloads(
        sources,
        class_level=args.class_level,
        lang=args.lang,
        include_documents=not args.no_documents,
    )
    logging.info("%d files planned", len(items))
    if not args.download:
        logging.info("dry run: pass --download to fetch into %s", args.dest)
        return 0
    fetcher = HttpxFetcher()
    try:
        results = download_all(items, args.dest, fetcher, log_path=args.log, delay=args.delay)
    finally:
        fetcher.close()
    counts = Counter(r.status for r in results)
    logging.info("done: %s", dict(counts))
    for result in results:
        if result.status in ("missing", "failed"):
            logging.warning("%s %s: %s", result.status, result.item.url, result.detail)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
