"""Load-test helpers: build signed webhook traffic and judge the results.

Pure functions only. scripts/load_test.py does the network calls and hands the outcomes here.
"""

import hashlib
import hmac
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

# Obviously fake Indian numbers (91 + 999900 + 4-digit index) so no real teacher is ever messaged.
SENDER_PREFIX = "91999900"
SENDER_INDEX_DIGITS = 4
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_END = 300
PERCENT = 100


@dataclass(frozen=True)
class Outcome:
    """One request: the HTTP status (None when the connection failed) and how long it took."""

    status: int | None
    latency_s: float

    @property
    def succeeded(self) -> bool:
        return self.status is not None and HTTP_SUCCESS_MIN <= self.status < HTTP_SUCCESS_END


@dataclass(frozen=True)
class LoadSummary:
    requests: int
    ok: int
    failed: int
    error_rate: float
    requests_per_s: float
    p50_s: float
    p95_s: float
    max_s: float


@dataclass(frozen=True)
class LoadBudget:
    p50_s: float
    p95_s: float
    max_error_rate: float


def sign_body(body: bytes, secret: str) -> str:
    """The X-Hub-Signature-256 value Meta would send for this exact body."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def webhook_body(*, sender: str, wamid: str, text: str) -> bytes:
    """A Meta-shaped inbound text message. Sign these exact bytes; do not re-serialise them."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }
    return json.dumps(payload).encode()


def fake_sender(index: int) -> str:
    return f"{SENDER_PREFIX}{index:0{SENDER_INDEX_DIGITS}d}"


def message_id(*, run: str, teacher: int, turn: int) -> str:
    """Unique per run: the webhook drops repeated ids for days, so a rerun must not reuse them."""
    return f"wamid.load.{run}.{teacher}.{turn}"


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0-100)."""
    if not values:
        raise ValueError("no samples")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered) / PERCENT))
    return ordered[rank - 1]


def summarise(outcomes: Sequence[Outcome], *, wall_s: float) -> LoadSummary:
    """Latency covers successful requests only, so a fast refusal cannot flatter the percentiles."""
    if not outcomes:
        raise ValueError("no requests")
    latencies = [o.latency_s for o in outcomes if o.succeeded]
    failed = len(outcomes) - len(latencies)
    return LoadSummary(
        requests=len(outcomes),
        ok=len(latencies),
        failed=failed,
        error_rate=failed / len(outcomes),
        requests_per_s=len(outcomes) / wall_s,
        p50_s=percentile(latencies, 50) if latencies else 0.0,
        p95_s=percentile(latencies, 95) if latencies else 0.0,
        max_s=max(latencies, default=0.0),
    )


def check_budget(summary: LoadSummary, budget: LoadBudget) -> list[str]:
    """One line per broken limit; an empty list means the run passed."""
    problems: list[str] = []
    if summary.p50_s > budget.p50_s:
        problems.append(f"p50 {summary.p50_s:.2f}s is over the {budget.p50_s:.2f}s budget")
    if summary.p95_s > budget.p95_s:
        problems.append(f"p95 {summary.p95_s:.2f}s is over the {budget.p95_s:.2f}s budget")
    if summary.error_rate > budget.max_error_rate:
        problems.append(
            f"error rate {summary.error_rate:.1%} is over the {budget.max_error_rate:.1%} budget"
        )
    return problems
