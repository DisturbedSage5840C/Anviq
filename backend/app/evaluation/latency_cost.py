"""Model latency per purpose and spend per teacher-day, from the usage tables. Plan section 8.

Targets: p50 <= 10 s and p95 <= 20 s end to end; <= US$0.12 per teacher-day. The `llm_usage`
rows give per-call model latency; end-to-end turn latency (speech, WhatsApp) comes from the load
test (`app.ops.loadtest_run`). A teacher-day is one teacher with at least one session that day.

    python -m app.evaluation.latency_cost --days 7 --inr-per-usd 84
"""

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import get_settings
from app.evaluation.metrics import percentile

COST_TARGET_USD = 0.12


async def measure(
    conn: AsyncConnection, since: datetime, inr_per_usd: Decimal
) -> dict[str, object]:
    latencies: dict[str, list[float]] = defaultdict(list)
    for purpose, latency in await conn.execute(
        text("select purpose, latency_ms from llm_usage where created_at >= :s"), {"s": since}
    ):
        latencies[purpose].append(float(latency))
    llm_usd = (
        await conn.execute(
            text("select coalesce(sum(est_cost_usd), 0) from llm_usage where created_at >= :s"),
            {"s": since},
        )
    ).scalar_one()
    speech_inr = (
        await conn.execute(
            text("select coalesce(sum(est_cost_inr), 0) from speech_usage where created_at >= :s"),
            {"s": since},
        )
    ).scalar_one()
    teacher_days = (
        await conn.execute(
            text(
                "select count(*) from (select distinct teacher_id, started_at::date "
                "from sessions where started_at >= :s) d"
            ),
            {"s": since},
        )
    ).scalar_one()
    total_usd = Decimal(llm_usd) + Decimal(speech_inr) / inr_per_usd
    per_day = float(total_usd / teacher_days) if teacher_days else None
    return {
        "since": since.isoformat(),
        "model_latency_ms": {
            p: {"calls": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95)}
            for p, v in sorted(latencies.items())
        },
        "llm_usd": float(llm_usd),
        "speech_usd": float(Decimal(speech_inr) / inr_per_usd),
        "teacher_days": teacher_days,
        "usd_per_teacher_day": per_day,
        "cost_pass": per_day is not None and per_day <= COST_TARGET_USD,
    }


async def _main(args: argparse.Namespace) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            since = datetime.now(UTC) - timedelta(days=args.days)
            report = await measure(conn, since, Decimal(str(args.inr_per_usd)))
    finally:
        await engine.dispose()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--inr-per-usd", type=float, default=84.0, help="an assumption; check it")
    parser.add_argument("--out", type=Path, default=Path("../eval/results/latency_cost.json"))
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
