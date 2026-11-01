"""Download PDFs politely and verifiably: slow, resumable, retried, and logged with a checksum.

The NCERT server sometimes resets connections, so a transient failure is retried with a growing
wait. A file is kept only if it starts with the PDF signature, which stops an error page being
saved as a book. Fetching is separate from the network client so it can be tested without one.
"""

import csv
import hashlib
import logging
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Protocol

import httpx

from app.core.ask.sources import DownloadItem

logger = logging.getLogger(__name__)

DEFAULT_DELAY = 1.0  # seconds between requests: one per second
DEFAULT_BACKOFF = 2.0
DEFAULT_RETRIES = 3  # attempts per file
REQUEST_TIMEOUT = 60.0
PDF_SIGNATURE = b"%PDF"
USER_AGENT = "anviq-corpus-fetch/1.0 (educational research; polite, 1 request per second)"
LOG_COLUMNS = ("date", "url", "relpath", "status", "bytes", "sha256")
_SERVER_ERROR = 500
_TOO_MANY_REQUESTS = 429


class FetchError(Exception):
    """The file cannot be had (for example it does not exist). Not retried."""


class TransientFetchError(FetchError):
    """A failure worth retrying: a reset connection, a timeout or a server error."""


class Fetcher(Protocol):
    def fetch(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class Result:
    item: DownloadItem
    status: str  # downloaded, skipped, missing or failed
    detail: str = ""


def system_trust_context() -> ssl.SSLContext:
    """A verifying TLS context that trusts what the operating system trusts.

    ncert.nic.in does not send its intermediate certificate. Browsers and curl fill the gap from
    the system store, but the certifi bundle httpx uses by default cannot, so every request fails
    verification. Using the system store fixes that without ever turning verification off.
    """
    import truststore  # imported here so tests and callers that inject a client never need it

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class HttpxFetcher:
    """The real fetcher: synchronous httpx with a neutral User-Agent and system certificates."""

    def __init__(
        self, timeout: float = REQUEST_TIMEOUT, client: httpx.Client | None = None
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            verify=system_trust_context(),
        )

    def fetch(self, url: str) -> bytes:
        try:
            response = self._client.get(url)
        except httpx.TransportError as exc:
            raise TransientFetchError(f"{type(exc).__name__}: {exc}") from exc
        code = response.status_code
        if code >= _SERVER_ERROR or code == _TOO_MANY_REQUESTS:
            raise TransientFetchError(f"HTTP {code}")
        if code >= httpx.codes.BAD_REQUEST:
            raise FetchError(f"HTTP {code}")
        return response.content

    def close(self) -> None:
        self._client.close()


def _safe_target(dest: Path, relpath: str) -> Path:
    posix = PurePosixPath(relpath)
    target = (dest / relpath).resolve()
    if posix.is_absolute() or ".." in posix.parts or not target.is_relative_to(dest.resolve()):
        raise ValueError(f"path {relpath!r} is outside the download folder")
    return target


def _append_log(log_path: Path, row: dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def _save(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(target)


def _fetch_with_retries(
    fetcher: Fetcher,
    url: str,
    *,
    retries: int,
    delay: float,
    backoff: float,
    sleep: Callable[[float], None],
) -> bytes:
    for attempt in range(1, retries + 1):
        try:
            return fetcher.fetch(url)
        except TransientFetchError as exc:
            if attempt == retries:
                raise
            wait = delay * backoff**attempt
            logger.warning("retry %d for %s in %.0fs: %s", attempt, url, wait, exc)
            sleep(wait)
    raise AssertionError("retries must be at least 1")  # pragma: no cover


def download_all(
    items: list[DownloadItem] | tuple[DownloadItem, ...],
    dest: Path,
    fetcher: Fetcher,
    *,
    log_path: Path,
    sleep: Callable[[float], None] = time.sleep,
    today: Callable[[], date] = date.today,
    delay: float = DEFAULT_DELAY,
    backoff: float = DEFAULT_BACKOFF,
    retries: int = DEFAULT_RETRIES,
) -> list[Result]:
    """Fetch each item not already on disk; one result per item, in order."""
    targets = [_safe_target(dest, item.relpath) for item in items]  # refuse bad paths first
    results: list[Result] = []
    requested = False
    for item, target in zip(items, targets, strict=True):
        if target.exists():
            results.append(Result(item, "skipped"))
            continue
        if requested:
            sleep(delay)
        requested = True
        result = _download_one(item, target, fetcher, retries, delay, backoff, sleep)
        _log(log_path, today(), item, result, target)
        results.append(result)
    return results


def _download_one(
    item: DownloadItem,
    target: Path,
    fetcher: Fetcher,
    retries: int,
    delay: float,
    backoff: float,
    sleep: Callable[[float], None],
) -> Result:
    try:
        data = _fetch_with_retries(
            fetcher, item.url, retries=retries, delay=delay, backoff=backoff, sleep=sleep
        )
    except TransientFetchError as exc:
        return Result(item, "failed", str(exc))
    except FetchError as exc:
        return Result(item, "missing", str(exc))
    if not data.startswith(PDF_SIGNATURE):
        return Result(item, "failed", "response is not a PDF")
    _save(target, data)
    return Result(item, "downloaded", hashlib.sha256(data).hexdigest())


def _log(log_path: Path, when: date, item: DownloadItem, result: Result, target: Path) -> None:
    downloaded = result.status == "downloaded"
    _append_log(
        log_path,
        {
            "date": when.isoformat(),
            "url": item.url,
            "relpath": item.relpath,
            "status": result.status,
            "bytes": target.stat().st_size if downloaded else "",
            "sha256": result.detail if downloaded else "",
        },
    )
