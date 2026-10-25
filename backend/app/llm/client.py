"""One wrapper around the Anthropic Messages API: caching, structured output, retries, usage.

Plan section 4.5. Everything that talks to a model goes through here, so there is one place that
retries, one place that records spend, and one place that must never log content. Errors carry
only the HTTP status. The usage row holds counts and cost, never a prompt or a reply.

Structured output uses a forced tool call: the model must "call" a tool whose input schema is the
pydantic model, and we validate what comes back. A reply that fails validation gets one repair
attempt that tells the model what was wrong, then `LLMError`.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})
MAX_ATTEMPTS = 3
FAST_TIMEOUT_S = 10.0
SMART_TIMEOUT_S = 20.0
RETRY_DELAY_S = 0.5

# US$ per million tokens (input, output). Assumptions, to be checked against the console on the
# first day with a key (plan section 7.5). A model we do not recognise is priced as Sonnet, the
# middle tier, so an unknown id never makes spend look lower than it is.
PRICES_PER_MTOK: Mapping[str, tuple[Decimal, Decimal]] = {
    # Matched by substring, in order, so the specific generations come before the generic tiers.
    "haiku-5": (Decimal("0.10"), Decimal("0.50")),
    "sonnet-5": (Decimal("2"), Decimal("10")),
    "opus-5": (Decimal("4"), Decimal("20")),
    "haiku-4": (Decimal("1"), Decimal("5")),
    "haiku": (Decimal("1"), Decimal("5")),
    "sonnet": (Decimal("3"), Decimal("15")),
    "opus": (Decimal("5"), Decimal("25")),
}
DEFAULT_TIER = "sonnet"
CACHE_READ_FACTOR = Decimal("0.1")
CACHE_WRITE_FACTOR = Decimal("1.25")
_PER_MTOK = Decimal(1_000_000)

T = TypeVar("T", bound=BaseModel)

ANSWER_VIA_TOOL = "Give your answer only by calling the `answer` tool, and write nothing else."


class LLMError(Exception):
    """The model call failed or returned something unusable. Never carries prompt or reply text."""


@dataclass(frozen=True)
class SystemBlock:
    """One part of the system prompt. `cache=True` marks the end of a large, stable prefix."""

    text: str
    cache: bool = False

    def as_api(self) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "text", "text": self.text}
        if self.cache:
            block["cache_control"] = {"type": "ephemeral"}
        return block


@dataclass(frozen=True)
class Usage:
    purpose: str
    model: str
    in_tok: int
    out_tok: int
    cache_read: int
    cache_write: int
    latency_ms: int
    est_cost_usd: Decimal


@dataclass(frozen=True)
class Reply:
    """The model's content blocks, as the API returned them, plus what the call cost."""

    blocks: tuple[Mapping[str, Any], ...]
    usage: Usage
    stop_reason: str = ""

    @property
    def text(self) -> str:
        return "".join(str(b.get("text", "")) for b in self.blocks if b.get("type") == "text")


class UsageSink(Protocol):
    async def record(self, usage: Usage) -> None: ...


def estimate_cost(
    model: str, in_tok: int, out_tok: int, cache_read: int, cache_write: int
) -> Decimal:
    tier = next((name for name in PRICES_PER_MTOK if name in model), DEFAULT_TIER)
    price_in, price_out = PRICES_PER_MTOK[tier]
    cost = (
        in_tok * price_in
        + cache_read * price_in * CACHE_READ_FACTOR
        + cache_write * price_in * CACHE_WRITE_FACTOR
        + out_tok * price_out
    ) / _PER_MTOK
    return cost.quantize(Decimal("0.000001"))


def _error_type(response: httpx.Response | None) -> str:
    """The API's short error class (e.g. invalid_request_error); never its message or body."""
    if response is None:
        return "none"
    try:
        kind = response.json()["error"]["type"]
    except (ValueError, KeyError, TypeError):
        return "unknown"
    return kind if isinstance(kind, str) and kind.isidentifier() else "unknown"


def _timeout_for(model: str) -> float:
    return FAST_TIMEOUT_S if "haiku" in model else SMART_TIMEOUT_S


class LLMClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        *,
        sink: UsageSink | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        base_url: str = API_URL,
    ) -> None:
        self._http = http
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        self._sink = sink
        self._sleep = sleep
        self._base_url = base_url

    async def complete(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int = 1024,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: Mapping[str, Any] | None = None,
        think: bool = True,
    ) -> Reply:
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [block.as_api() for block in system],
            "messages": list(messages),
        }
        if not think:
            # Short replies on a small token cap: adaptive thinking would eat the whole budget.
            body["thinking"] = {"type": "disabled"}
        if tools:
            body["tools"] = list(tools)
        if tool_choice:
            body["tool_choice"] = dict(tool_choice)
        started = time.monotonic()
        data = await self._post(body, _timeout_for(model))
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = self._usage(purpose, model, data, latency_ms)
        if self._sink is not None:
            await self._sink.record(usage)
        return Reply(tuple(data.get("content", ())), usage, str(data.get("stop_reason") or ""))

    async def complete_text(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int = 512,
        think: bool = True,
    ) -> str:
        reply = await self.complete(
            purpose,
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            think=think,
        )
        text = reply.text.strip()
        if not text and reply.stop_reason == "max_tokens":
            logger.error("llm_cut_off purpose=%s max_tokens=%d", purpose, max_tokens)
            raise LLMError(f"{purpose}: reply cut off before any text")
        return text

    async def complete_json(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        schema: type[T],
        max_tokens: int = 1024,
        think: bool = True,
    ) -> T:
        tool = {
            "name": "answer",
            "description": "Give your answer in exactly this structure.",
            "input_schema": schema.model_json_schema(),
        }
        # Current models refuse a forced tool, so the tool is offered and the prompt asks for it.
        # A reply in prose lands in the one repair attempt below.
        system = [*system, SystemBlock(ANSWER_VIA_TOOL)]
        convo = list(messages)
        problem = ""
        for attempt in range(2):
            reply = await self.complete(
                purpose,
                model=model,
                system=system,
                messages=convo,
                max_tokens=max_tokens,
                tools=[tool],
                tool_choice={"type": "auto"},
                think=think,
            )
            call = next((b for b in reply.blocks if b.get("type") == "tool_use"), None)
            if call is None:
                problem = "no structured answer was returned"
            else:
                try:
                    return schema.model_validate(call.get("input", {}))
                except ValidationError as exc:
                    problem = _short_problem(exc)
            if attempt == 0:
                convo = [*messages, *_repair_turns(reply.blocks, problem)]
        raise LLMError(f"{purpose}: structured answer rejected ({problem})")

    async def _post(self, body: Mapping[str, Any], timeout_s: float) -> dict[str, Any]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._http.post(
                    self._base_url, headers=self._headers, json=body, timeout=timeout_s
                )
            except httpx.HTTPError:
                response = None
            status = "network error" if response is None else str(response.status_code)
            if response is not None and response.status_code < 400:
                return self._decode(response)
            retryable = response is None or response.status_code in RETRYABLE_STATUS
            if not retryable or attempt == MAX_ATTEMPTS:
                logger.error("llm_failed status=%s type=%s", status, _error_type(response))
                raise LLMError(f"model request failed: {status}")
            logger.warning("llm_retry attempt=%d status=%s", attempt, status)
            await self._sleep(RETRY_DELAY_S * 2 ** (attempt - 1))
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            raise LLMError("model response was not JSON") from None
        if not isinstance(data, dict):
            raise LLMError("model response was not an object")
        return data

    @staticmethod
    def _usage(purpose: str, model: str, data: Mapping[str, Any], latency_ms: int) -> Usage:
        raw = data.get("usage") or {}
        in_tok = int(raw.get("input_tokens", 0))
        out_tok = int(raw.get("output_tokens", 0))
        cache_read = int(raw.get("cache_read_input_tokens", 0))
        cache_write = int(raw.get("cache_creation_input_tokens", 0))
        return Usage(
            purpose=purpose,
            model=model,
            in_tok=in_tok,
            out_tok=out_tok,
            cache_read=cache_read,
            cache_write=cache_write,
            latency_ms=latency_ms,
            est_cost_usd=estimate_cost(model, in_tok, out_tok, cache_read, cache_write),
        )


def _short_problem(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "answer"
    return f"{where}: {first['type']}"


def _repair_turns(blocks: Sequence[Mapping[str, Any]], problem: str) -> list[dict[str, Any]]:
    """The turns that ask for a second try: the model's reply (if it said anything) and a nudge."""
    note = f"That answer was not accepted ({problem}). Answer again in the required structure."
    said = [{"role": "assistant", "content": [dict(b) for b in blocks]}] if blocks else []
    call = next((b for b in blocks if b.get("type") == "tool_use"), None)
    if call is None:
        return [*said, {"role": "user", "content": note}]
    result = {"type": "tool_result", "tool_use_id": call["id"], "content": note, "is_error": True}
    return [*said, {"role": "user", "content": [result]}]


def dumps_compact(value: object) -> str:
    """JSON for embedding data in a prompt: compact and unicode-preserving (Hindi stays Hindi)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
