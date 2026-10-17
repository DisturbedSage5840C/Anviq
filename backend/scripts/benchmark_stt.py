"""Compare STT providers on a labelled clip set (Day-3 decision).

Usage:
    uv run python scripts/benchmark_stt.py eval/datasets/stt_clips/manifest.csv

The manifest has columns clip,reference,lang,condition. Keys come from the environment
(SARVAM_API_KEY, GOOGLE_SPEECH_API_KEY); a provider without a key is skipped. Clips are
sent to the vendors, so use only consented or synthetic recordings.
"""

import asyncio
import sys
import time
from pathlib import Path

import httpx

from app.channel.audio import prepare_for_stt
from app.config import get_settings
from app.speech.base import STTProvider
from app.speech.benchmark import Clip, ClipResult, load_manifest, summarise
from app.speech.google import GoogleSTT
from app.speech.sarvam import SarvamSTT

# INR/hour for Sarvam, USD/hour for Google: units differ, so compare the cost columns with care.
# Verify both against the vendors' price pages before quoting them.
COST_PER_HOUR = {"sarvam": 30.0, "google": 0.96}
FAILED = "<failed>"


async def _run_clip(provider_name: str, stt: STTProvider, clip: Clip) -> ClipResult:
    prepared = prepare_for_stt(clip.path.read_bytes())
    started = time.perf_counter()
    try:
        hypothesis = (await stt.transcribe(prepared, lang_hint=clip.lang)).text
    except Exception as exc:  # noqa: BLE001 - a failing clip must not stop the benchmark
        print(f"  {provider_name} failed on {clip.path.name}: {type(exc).__name__}")
        hypothesis = FAILED
    return ClipResult(
        provider=provider_name,
        clip_id=clip.path.name,
        condition=clip.condition,
        reference=clip.reference,
        hypothesis=hypothesis,
        latency_s=time.perf_counter() - started,
        audio_s=prepared.duration_s,
    )


def _providers(http: httpx.AsyncClient) -> dict[str, STTProvider]:
    settings = get_settings()
    providers: dict[str, STTProvider] = {}
    if settings.sarvam_api_key is not None:
        providers["sarvam"] = SarvamSTT(
            http,
            api_key=settings.sarvam_api_key.get_secret_value(),
            model=settings.sarvam_stt_model,
        )
    if settings.google_speech_api_key is not None:
        providers["google"] = GoogleSTT(
            http, api_key=settings.google_speech_api_key.get_secret_value()
        )
    return providers


async def main(manifest: Path) -> None:
    clips = load_manifest(manifest)
    async with httpx.AsyncClient(timeout=60.0) as http:
        providers = _providers(http)
        if not providers:
            sys.exit("No speech API keys configured (SARVAM_API_KEY / GOOGLE_SPEECH_API_KEY).")
        results = [
            await _run_clip(name, stt, clip) for name, stt in providers.items() for clip in clips
        ]
    print(f"\n{'provider':<8} {'clips':>5} {'WER':>6} {'CER':>6} {'latency':>8} {'cost':>8}")
    for row in summarise(results, cost_per_hour=COST_PER_HOUR):
        cost = "n/a" if row.cost is None else f"{row.cost:.3f}"
        print(
            f"{row.provider:<8} {row.clips:>5} {row.mean_wer:>6.1%} {row.mean_cer:>6.1%} "
            f"{row.mean_latency_s:>7.2f}s {cost:>8}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(Path(sys.argv[1])))
