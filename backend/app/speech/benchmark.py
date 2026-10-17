"""STT benchmark data model: manifest loading and per-provider summaries."""

import csv
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.speech.metrics import cer, wer

REQUIRED_COLUMNS = ("clip", "reference", "lang", "condition")
SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Clip:
    path: Path
    reference: str
    lang: str
    condition: str


@dataclass(frozen=True)
class ClipResult:
    provider: str
    clip_id: str
    condition: str
    reference: str
    hypothesis: str
    latency_s: float
    audio_s: float


@dataclass(frozen=True)
class ProviderSummary:
    provider: str
    clips: int
    mean_wer: float
    mean_cer: float
    mean_latency_s: float
    cost: float | None


def load_manifest(manifest: Path) -> tuple[Clip, ...]:
    with manifest.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Manifest is missing columns: {', '.join(missing)}")
        return tuple(
            Clip(
                path=manifest.parent / row["clip"],
                reference=row["reference"],
                lang=row["lang"],
                condition=row["condition"],
            )
            for row in reader
        )


def summarise(
    results: Iterable[ClipResult], *, cost_per_hour: Mapping[str, float]
) -> tuple[ProviderSummary, ...]:
    by_provider: dict[str, list[ClipResult]] = defaultdict(list)
    for result in results:
        by_provider[result.provider].append(result)
    return tuple(
        _summarise_provider(provider, rows, cost_per_hour.get(provider))
        for provider, rows in by_provider.items()
    )


def _summarise_provider(
    provider: str, rows: list[ClipResult], rate_per_hour: float | None
) -> ProviderSummary:
    count = len(rows)
    audio_s = sum(row.audio_s for row in rows)
    return ProviderSummary(
        provider=provider,
        clips=count,
        mean_wer=sum(wer(row.reference, row.hypothesis) for row in rows) / count,
        mean_cer=sum(cer(row.reference, row.hypothesis) for row in rows) / count,
        mean_latency_s=sum(row.latency_s for row in rows) / count,
        cost=None if rate_per_hour is None else rate_per_hour * audio_s / SECONDS_PER_HOUR,
    )
