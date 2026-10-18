"""Drive simulated teachers against a running Anviq and time every request.

Two modes, because they measure different things:
- webhook: signed WhatsApp messages. The API only verifies and queues, so this times the ack Meta
  waits for. Replies leave through Meta and cannot be observed from here.
- web: /web/turn with demo codes. The reply comes back in the response, so this times the whole
  turn (speech, routing, reply) the way a visitor feels it.

Teachers run side by side; each one sends its own turns one after another, like a person would.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from urllib.parse import urlparse

import httpx

from app.ops.loadtest import Outcome, fake_sender, message_id, sign_body, webhook_body

WEBHOOK_PATH = "/webhook/whatsapp"
WEB_TURN_PATH = "/web/turn"
SIGNATURE_HEADER = "X-Hub-Signature-256"
DEMO_CODE_HEADER = "X-Demo-Code"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"
PRODUCTION_MARKER = "prod"

SAMPLE_LINES = (
    "नमस्ते, कल मुझे गिनती पढ़ानी है",
    "Tomorrow I teach counting to Grade 2",
    "मैं बच्चों को जोड़ना कैसे सिखाऊँ?",
    "I want to practise a lesson on the letter A",
)

Send = Callable[[int], Awaitable[httpx.Response]]


def is_production_host(base_url: str) -> bool:
    """True when the URL looks like prod, so a load test is not pointed at real teachers."""
    host = urlparse(base_url).hostname or ""
    return PRODUCTION_MARKER in host.lower()


def _line(turn: int) -> str:
    return SAMPLE_LINES[turn % len(SAMPLE_LINES)]


async def _timed(request: Awaitable[httpx.Response]) -> Outcome:
    started = time.perf_counter()
    try:
        response = await request
    except httpx.HTTPError:
        return Outcome(status=None, latency_s=time.perf_counter() - started)
    return Outcome(status=response.status_code, latency_s=time.perf_counter() - started)


async def _teacher(send: Send, *, turns: int, think_s: float) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for turn in range(turns):
        if turn:
            await asyncio.sleep(think_s)
        outcomes.append(await _timed(send(turn)))
    return outcomes


async def _all_teachers(sends: Sequence[Send], *, turns: int, think_s: float) -> list[Outcome]:
    per_teacher = await asyncio.gather(*(_teacher(s, turns=turns, think_s=think_s) for s in sends))
    return [outcome for outcomes in per_teacher for outcome in outcomes]


def _post_webhook(
    client: httpx.AsyncClient, secret: str, run: str, teacher: int, turn: int
) -> Awaitable[httpx.Response]:
    body = webhook_body(
        sender=fake_sender(teacher),
        wamid=message_id(run=run, teacher=teacher, turn=turn),
        text=_line(turn),
    )
    return client.post(
        WEBHOOK_PATH,
        content=body,
        headers={SIGNATURE_HEADER: sign_body(body, secret), "Content-Type": "application/json"},
    )


def _post_web(client: httpx.AsyncClient, code: str, turn: int) -> Awaitable[httpx.Response]:
    return client.post(
        WEB_TURN_PATH,
        content=_line(turn).encode("utf-8"),
        headers={DEMO_CODE_HEADER: code, "Content-Type": TEXT_CONTENT_TYPE},
    )


async def run_turns_webhook(
    client: httpx.AsyncClient,
    *,
    secret: str,
    run: str,
    teachers: int,
    turns: int,
    think_s: float,
) -> list[Outcome]:
    sends = [partial(_post_webhook, client, secret, run, teacher) for teacher in range(teachers)]
    return await _all_teachers(sends, turns=turns, think_s=think_s)


async def run_turns_web(
    client: httpx.AsyncClient, *, codes: Sequence[str], turns: int, think_s: float
) -> list[Outcome]:
    """One simulated teacher per demo code; each code must have at least `turns` turns left."""
    sends = [partial(_post_web, client, code) for code in codes]
    return await _all_teachers(sends, turns=turns, think_s=think_s)
