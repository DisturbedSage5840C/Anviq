"""A deterministic price for one assumed teacher-day, from measured per-call token averages.

The stored `latency_cost.json` figure divides real spend by real teacher-days, but the demo had
only 2 teacher-days of mostly test traffic, so it says little. This module prices a fixed,
written-down day instead: the same calls every time, at the current price table and Google
speech rates, so the figure can be re-checked and compared when a lever changes.

    python -m app.evaluation.assumed_day --out ../eval/results/assumed_day.json

The token averages are per-call means read from the demo VM's `llm_usage` table on 28 Oct 2026
(4 to 74 calls per purpose). The day itself (how many calls, seconds and characters) is an
assumption, not a measurement; change `ASSUMED_DAY` and the figure follows.
"""

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from app.llm.client import estimate_cost
from app.speech.metering import stt_cost_inr, tts_cost_inr

COST_TARGET_USD = 0.12
SPEECH_PROVIDER = "google"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


@dataclass(frozen=True)
class CallProfile:
    """Mean tokens of one call: uncached input, output, cache reads, cache writes."""

    model: str
    in_tok: int
    out_tok: int
    cache_read: int
    cache_write: int


MEASURED_PROFILES: Mapping[str, CallProfile] = {
    "coach": CallProfile(SONNET, 300, 510, 1020, 510),
    "child": CallProfile(HAIKU, 301, 71, 180, 182),
    "plan": CallProfile(SONNET, 568, 441, 250, 749),
    "topic": CallProfile(HAIKU, 147, 92, 377, 251),
    "reflect": CallProfile(SONNET, 171, 221, 0, 752),
    "ask_rewrite": CallProfile(HAIKU, 162, 192, 535, 63),
    "ask_answer": CallProfile(SONNET, 11709, 321, 890, 127),
}


@dataclass(frozen=True)
class AssumedDay:
    calls: Mapping[str, int]
    stt_seconds: int
    tts_characters: int


# 5 rehearsal turns (8 s of teacher speech each), 1 plan (10 s), 1 reflection (30 s) and 1
# in-scope question (10 s); about 3,000 spoken characters in all (docs/free-demo-deploy.md).
ASSUMED_DAY = AssumedDay(
    calls={
        "coach": 5,
        "child": 5,
        "plan": 1,
        "topic": 1,
        "reflect": 1,
        "ask_rewrite": 1,
        "ask_answer": 1,
    },
    stt_seconds=5 * 8 + 10 + 30 + 10,
    tts_characters=3000,
)


def price_day(
    day: AssumedDay,
    inr_per_usd: Decimal,
    model_overrides: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Price `day`; `model_overrides` re-prices a purpose on another model (same token counts)."""
    overrides = model_overrides or {}
    by_purpose: dict[str, Decimal] = {}
    for purpose, count in day.calls.items():
        p = MEASURED_PROFILES[purpose]
        model = overrides.get(purpose, p.model)
        unit = estimate_cost(model, p.in_tok, p.out_tok, p.cache_read, p.cache_write)
        by_purpose[purpose] = unit * count
    llm_usd = sum(by_purpose.values(), Decimal(0))
    speech_inr = stt_cost_inr(SPEECH_PROVIDER, Decimal(day.stt_seconds)) + tts_cost_inr(
        SPEECH_PROVIDER, day.tts_characters
    )
    speech_usd = speech_inr / inr_per_usd
    total = float(llm_usd + speech_usd)
    return {
        "llm_usd": float(llm_usd),
        "speech_usd": float(speech_usd),
        "by_purpose_usd": {k: float(v) for k, v in by_purpose.items()},
        "usd_per_teacher_day": total,
        "cost_pass": total <= COST_TARGET_USD,
    }


@dataclass(frozen=True)
class Scenario:
    name: str
    overrides: Mapping[str, str] = field(default_factory=dict)


SCENARIOS = (
    Scenario("as deployed"),
    Scenario("coach on Haiku (not adopted)", {"coach": HAIKU}),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inr-per-usd", type=float, default=84.0, help="an assumption; check it")
    parser.add_argument("--out", type=Path, default=Path("../eval/results/assumed_day.json"))
    args = parser.parse_args()
    rate = Decimal(str(args.inr_per_usd))
    report = {
        "assumed_day": {
            "calls": dict(ASSUMED_DAY.calls),
            "stt_seconds": ASSUMED_DAY.stt_seconds,
            "tts_characters": ASSUMED_DAY.tts_characters,
        },
        "inr_per_usd": args.inr_per_usd,
        "target_usd": COST_TARGET_USD,
        "scenarios": {s.name: price_day(ASSUMED_DAY, rate, s.overrides) for s in SCENARIOS},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, result in report["scenarios"].items():
        print(f"{name}: ${result['usd_per_teacher_day']:.3f}")


if __name__ == "__main__":
    main()
