"""Simulate many teachers against a running Anviq and check latency and error budgets.

    WA_APP_SECRET=... uv run python -m scripts.load_test --base-url $STAGING_URL webhook
    LOAD_DEMO_CODES=a,b,c uv run python -m scripts.load_test --base-url $STAGING_URL web

webhook mode posts signed WhatsApp messages from fake numbers and times the ack. It creates fake
teacher rows in the target database, and the replies to those numbers will fail at Meta, so only
point it at staging. web mode times whole turns through /web/turn; each demo code is one teacher
and needs at least --turns turns left (python -m app.web.issue_code --turns N).

Exit code: 0 within budget, 1 over budget, 2 refused (bad arguments or a production host).
"""

import argparse
import asyncio
import os
import secrets
import sys
import time
from collections.abc import Sequence
from dataclasses import replace

import httpx

from app.ops.loadtest import LoadBudget, LoadSummary, Outcome, check_budget, summarise
from app.ops.loadtest_run import is_production_host, run_turns_web, run_turns_webhook

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_REFUSED = 2

# The webhook only verifies and queues, so it should answer in well under a second.
WEBHOOK_BUDGET = LoadBudget(p50_s=0.5, p95_s=1.0, max_error_rate=0.01)
# The plan's end-to-end target for a whole web turn.
WEB_BUDGET = LoadBudget(p50_s=10.0, p95_s=20.0, max_error_rate=0.01)

DEFAULT_TEACHERS = 50
DEFAULT_TURNS = 5
DEFAULT_THINK_S = 2.0
DEFAULT_TIMEOUT_S = 60.0
# Both the webhook and the web room cap a sender or code at 60 turns an hour.
MAX_TURNS = 60
RUN_ID_BYTES = 4


class Refused(Exception):
    """The run was not started; the message says why."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("mode", choices=("webhook", "web"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--teachers", type=int, default=DEFAULT_TEACHERS)
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--think-s", type=float, default=DEFAULT_THINK_S)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--p50", type=float, help="p50 budget in seconds")
    parser.add_argument("--p95", type=float, help="p95 budget in seconds")
    parser.add_argument("--max-error-rate", type=float, help="0.01 means 1%%")
    parser.add_argument("--allow-prod", action="store_true")
    return parser


def _budget(args: argparse.Namespace) -> LoadBudget:
    base = WEBHOOK_BUDGET if args.mode == "webhook" else WEB_BUDGET
    overrides = {
        "p50_s": args.p50,
        "p95_s": args.p95,
        "max_error_rate": args.max_error_rate,
    }
    return replace(base, **{k: v for k, v in overrides.items() if v is not None})


def _validate(args: argparse.Namespace) -> None:
    if is_production_host(args.base_url) and not args.allow_prod:
        raise Refused("that looks like a production host; pass --allow-prod only if you mean it")
    if args.teachers < 1:
        raise Refused("--teachers must be at least 1")
    if not 1 <= args.turns <= MAX_TURNS:
        raise Refused(f"--turns must be between 1 and {MAX_TURNS} (the hourly rate limit)")


def _demo_codes(teachers: int) -> list[str]:
    codes = [c.strip() for c in os.environ.get("LOAD_DEMO_CODES", "").split(",") if c.strip()]
    if not codes:
        raise Refused("set LOAD_DEMO_CODES to a comma-separated list of demo codes")
    return codes[:teachers]


def _app_secret() -> str:
    value = os.environ.get("WA_APP_SECRET", "")
    if not value:
        raise Refused("set WA_APP_SECRET to the target's WhatsApp app secret")
    return value


async def _drive(args: argparse.Namespace) -> list[Outcome]:
    timeout = httpx.Timeout(args.timeout_s)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        if args.mode == "webhook":
            return await run_turns_webhook(
                client,
                secret=_app_secret(),
                run=secrets.token_hex(RUN_ID_BYTES),
                teachers=args.teachers,
                turns=args.turns,
                think_s=args.think_s,
            )
        return await run_turns_web(
            client, codes=_demo_codes(args.teachers), turns=args.turns, think_s=args.think_s
        )


def _report(summary: LoadSummary, problems: Sequence[str]) -> None:
    print(f"requests   {summary.requests} ({summary.ok} ok, {summary.failed} failed)")
    print(f"error rate {summary.error_rate:.1%}")
    print(f"throughput {summary.requests_per_s:.1f} req/s")
    print(
        f"latency    p50 {summary.p50_s:.2f}s  p95 {summary.p95_s:.2f}s  max {summary.max_s:.2f}s"
    )
    if not problems:
        print("PASS")
        return
    print("FAIL")
    for problem in problems:
        print(f"  - {problem}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate(args)
        budget = _budget(args)
        started = time.perf_counter()
        outcomes = asyncio.run(_drive(args))
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    summary = summarise(outcomes, wall_s=time.perf_counter() - started)
    problems = check_budget(summary, budget)
    _report(summary, problems)
    return EXIT_OVER_BUDGET if problems else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
