from decimal import Decimal

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.client import (
    API_URL,
    LLMClient,
    LLMError,
    SystemBlock,
    Usage,
    estimate_cost,
)

SYSTEM = [SystemBlock("be kind", cache=True)]
MESSAGES = [{"role": "user", "content": "hi"}]
USAGE = {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_read_input_tokens": 1000,
    "cache_creation_input_tokens": 200,
}


class Sink:
    def __init__(self) -> None:
        self.rows: list[Usage] = []

    async def record(self, usage: Usage) -> None:
        self.rows.append(usage)


async def no_sleep(_: float) -> None:
    return None


class Verdict(BaseModel):
    ok: bool
    note: str


def tool_reply(payload: dict[str, object], block_id: str = "tu_1") -> dict[str, object]:
    return {
        "content": [{"type": "tool_use", "id": block_id, "name": "answer", "input": payload}],
        "usage": USAGE,
    }


@pytest.fixture
def sink() -> Sink:
    return Sink()


@pytest.fixture
async def client(sink: Sink):
    async with httpx.AsyncClient() as http:
        yield LLMClient(http, "sk-test", sink=sink, sleep=no_sleep)


@respx.mock
async def test_text_reply_sends_cached_system_and_records_usage(client: LLMClient, sink: Sink):
    route = respx.post(API_URL).respond(
        json={"content": [{"type": "text", "text": " नमस्ते "}], "usage": USAGE}
    )
    text = await client.complete_text(
        "child", model="claude-haiku-5-5", system=SYSTEM, messages=MESSAGES
    )
    assert text == "नमस्ते"
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "sk-test"
    body = sent.read().decode()
    assert '"cache_control":{"type":"ephemeral"}' in body.replace(" ", "")
    (row,) = sink.rows
    assert (row.purpose, row.in_tok, row.out_tok, row.cache_read, row.cache_write) == (
        "child",
        100,
        50,
        1000,
        200,
    )
    assert row.est_cost_usd > 0


@respx.mock
async def test_retries_rate_limits_then_succeeds(client: LLMClient):
    route = respx.post(API_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(529),
            httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]}),
        ]
    )
    assert await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES) == "ok"
    assert route.call_count == 3


@respx.mock
async def test_gives_up_with_status_only_error(client: LLMClient):
    respx.post(API_URL).respond(503, text="secret prompt echoed back")
    with pytest.raises(LLMError) as err:
        await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES)
    assert str(err.value) == "model request failed: 503"


@respx.mock
async def test_client_error_is_not_retried(client: LLMClient):
    route = respx.post(API_URL).respond(400)
    with pytest.raises(LLMError):
        await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES)
    assert route.call_count == 1


@respx.mock
async def test_network_failure_is_retried_then_reported(client: LLMClient):
    respx.post(API_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(LLMError, match="network error"):
        await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES)


@respx.mock
async def test_json_answer_is_validated_into_the_schema(client: LLMClient):
    route = respx.post(API_URL).respond(json=tool_reply({"ok": True, "note": "fine"}))
    verdict = await client.complete_json(
        "coach", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict
    )
    assert verdict == Verdict(ok=True, note="fine")
    sent = route.calls.last.request.read().decode()
    assert '"tool_choice"' in sent and '"input_schema"' in sent


@respx.mock
async def test_invalid_json_gets_one_repair_attempt(client: LLMClient):
    route = respx.post(API_URL).mock(
        side_effect=[
            httpx.Response(200, json=tool_reply({"ok": "maybe"})),
            httpx.Response(200, json=tool_reply({"ok": False, "note": "fixed"}, "tu_2")),
        ]
    )
    verdict = await client.complete_json(
        "coach", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict
    )
    assert verdict.note == "fixed"
    assert route.call_count == 2
    second = route.calls.last.request.read().decode()
    assert "tool_result" in second and "is_error" in second


@respx.mock
async def test_still_invalid_after_repair_is_an_error_without_content(client: LLMClient):
    respx.post(API_URL).respond(json=tool_reply({"ok": "maybe"}))
    with pytest.raises(LLMError) as err:
        await client.complete_json(
            "coach", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict
        )
    assert "maybe" not in str(err.value)


@respx.mock
async def test_missing_tool_call_is_repaired_with_a_plain_nudge(client: LLMClient):
    route = respx.post(API_URL).mock(
        side_effect=[
            httpx.Response(200, json={"content": [{"type": "text", "text": "hm"}]}),
            httpx.Response(200, json=tool_reply({"ok": True, "note": "n"})),
        ]
    )
    verdict = await client.complete_json(
        "coach", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict
    )
    assert verdict.ok
    assert route.call_count == 2


def test_cost_uses_tier_and_cache_discounts():
    haiku = estimate_cost("claude-haiku-5-5", 1_000_000, 0, 0, 0)
    assert haiku == Decimal("1.000000")
    assert estimate_cost("claude-haiku-5-5", 0, 0, 1_000_000, 0) == Decimal("0.100000")
    assert estimate_cost("claude-haiku-5-5", 0, 0, 0, 1_000_000) == Decimal("1.250000")


def test_unknown_model_is_priced_as_sonnet():
    assert estimate_cost("mystery", 1_000_000, 0, 0, 0) == Decimal("3.000000")
