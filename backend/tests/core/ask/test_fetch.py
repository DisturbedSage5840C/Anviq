import csv
from datetime import date

import pytest

from app.core.ask.fetch import (
    FetchError,
    TransientFetchError,
    download_all,
)
from app.core.ask.sources import DownloadItem

PDF = b"%PDF-1.7 hello"


class FakeFetcher:
    def __init__(self, script: dict[str, list[object]]) -> None:
        self._script = {url: list(steps) for url, steps in script.items()}
        self.calls: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        steps = self._script[url]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(step, Exception):
            raise step
        assert isinstance(step, bytes)
        return step


def _item(name: str = "a.pdf") -> DownloadItem:
    return DownloadItem(url=f"https://x/{name}", relpath=f"books/b/{name}")


def _run(items, fetcher, tmp_path, sleeps=None, **kwargs):
    sleeps = sleeps if sleeps is not None else []
    return download_all(
        items,
        tmp_path / "raw",
        fetcher,
        log_path=tmp_path / "log.csv",
        sleep=sleeps.append,
        today=lambda: date(2026, 11, 1),
        **kwargs,
    )


def test_downloads_validates_and_logs_a_pdf(tmp_path):
    item = _item()

    [result] = _run([item], FakeFetcher({item.url: [PDF]}), tmp_path)

    assert result.status == "downloaded"
    assert (tmp_path / "raw" / item.relpath).read_bytes() == PDF
    [row] = list(csv.DictReader((tmp_path / "log.csv").open(encoding="utf-8")))
    assert row["url"] == item.url
    assert row["date"] == "2026-11-01"
    assert len(row["sha256"]) == 64


def test_a_file_that_is_not_a_pdf_is_rejected_and_not_saved(tmp_path):
    item = _item()

    [result] = _run([item], FakeFetcher({item.url: [b"<html>blocked</html>"]}), tmp_path)

    assert result.status == "failed"
    assert not (tmp_path / "raw" / item.relpath).exists()


def test_existing_files_are_skipped_without_a_request(tmp_path):
    item = _item()
    target = tmp_path / "raw" / item.relpath
    target.parent.mkdir(parents=True)
    target.write_bytes(PDF)
    fetcher = FakeFetcher({item.url: [PDF]})

    [result] = _run([item], fetcher, tmp_path)

    assert result.status == "skipped"
    assert fetcher.calls == []


def test_connection_resets_are_retried_with_growing_backoff(tmp_path):
    item = _item()
    reset = TransientFetchError("connection reset")
    fetcher = FakeFetcher({item.url: [reset, reset, PDF]})
    sleeps: list[float] = []

    [result] = _run([item], fetcher, tmp_path, sleeps, delay=1.0, backoff=2.0)

    assert result.status == "downloaded"
    assert len(fetcher.calls) == 3
    assert sleeps[:2] == [2.0, 4.0]


def test_retries_are_bounded(tmp_path):
    item = _item()
    fetcher = FakeFetcher({item.url: [TransientFetchError("reset")]})

    [result] = _run([item], fetcher, tmp_path, retries=3)

    assert result.status == "failed"
    assert len(fetcher.calls) == 3


def test_a_missing_file_is_recorded_and_not_retried(tmp_path):
    item = _item()
    fetcher = FakeFetcher({item.url: [FetchError("HTTP 404")]})

    [result] = _run([item], fetcher, tmp_path)

    assert result.status == "missing"
    assert len(fetcher.calls) == 1


def test_requests_are_spaced_by_the_delay(tmp_path):
    first, second = _item("a.pdf"), _item("b.pdf")
    fetcher = FakeFetcher({first.url: [PDF], second.url: [PDF]})
    sleeps: list[float] = []

    _run([first, second], fetcher, tmp_path, sleeps, delay=1.0)

    assert sleeps == [1.0]


@pytest.mark.parametrize("relpath", ["../escape.pdf", "/abs.pdf", "a/../../b.pdf"])
def test_paths_that_leave_the_download_folder_are_refused(tmp_path, relpath):
    item = DownloadItem(url="https://x/a.pdf", relpath=relpath)

    with pytest.raises(ValueError, match="outside"):
        _run([item], FakeFetcher({item.url: [PDF]}), tmp_path)


def test_download_all_does_not_mutate_its_input(tmp_path):
    items = [_item()]
    snapshot = list(items)

    _run(items, FakeFetcher({items[0].url: [PDF]}), tmp_path)

    assert items == snapshot
