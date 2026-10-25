import json
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
async def test_a_refused_request_is_logged_by_status_and_type_only(
    client: LLMClient, caplog: pytest.LogCaptureFixture
):
    respx.post(API_URL).respond(
        400,
        json={"error": {"type": "invalid_request_error", "message": "secret prompt echoed back"}},
    )

    with caplog.at_level("ERROR", logger="app.llm.client"), pytest.raises(LLMError):
        await client.complete_text("coach", model="m", system=SYSTEM, messages=MESSAGES)

    assert "status=400" in caplog.text
    assert "invalid_request_error" in caplog.text
    assert "secret prompt" not in caplog.text


@respx.mock
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (httpx.Response(400, text="not json at all"), "type=unknown"),
        (httpx.Response(400, json={"error": {"type": "bad\nline injected"}}), "type=unknown"),
        (httpx.Response(400, json={"error": "flat"}), "type=unknown"),
        (httpx.ConnectError("boom"), "type=none"),
    ],
)
async def test_an_odd_failure_is_logged_without_echoing_what_the_server_said(
    client: LLMClient, caplog: pytest.LogCaptureFixture, reply, expected: str
):
    if isinstance(reply, Exception):
        respx.post(API_URL).mock(side_effect=reply)
    else:
        respx.post(API_URL).mock(return_value=reply)

    with caplog.at_level("ERROR", logger="app.llm.client"), pytest.raises(LLMError):
        await client.complete_text("coach", model="m", system=SYSTEM, messages=MESSAGES)

    assert expected in caplog.text
    assert "injected" not in caplog.text and "not json" not in caplog.text


@respx.mock
async def test_a_retried_failure_is_logged_as_failed_once(
    client: LLMClient, caplog: pytest.LogCaptureFixture
):
    respx.post(API_URL).respond(503)

    with caplog.at_level("ERROR", logger="app.llm.client"), pytest.raises(LLMError):
        await client.complete_text("coach", model="m", system=SYSTEM, messages=MESSAGES)

    assert caplog.text.count("llm_failed") == 1


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
async def test_no_request_carries_a_temperature_because_current_models_reject_it(
    client: LLMClient,
):
    route = respx.post(API_URL).respond(
        json={**tool_reply({"ok": True, "note": "n"}), "stop_reason": "tool_use"}
    )

    await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES)
    await client.complete_json("x", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict)

    for call in route.calls:
        assert "temperature" not in json.loads(call.request.read())


@respx.mock
async def test_json_answer_does_not_force_the_tool_because_newer_models_refuse_that(
    client: LLMClient,
):
    route = respx.post(API_URL).respond(json=tool_reply({"ok": True, "note": "n"}))

    await client.complete_json("x", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict)

    body = json.loads(route.calls.last.request.read())
    assert body["tool_choice"] == {"type": "auto"}
    assert "`answer`" in body["system"][-1]["text"]


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


@respx.mock
async def test_an_empty_reply_is_repaired_without_an_empty_assistant_turn(client: LLMClient):
    route = respx.post(API_URL).mock(
        side_effect=[
            httpx.Response(200, json={"content": []}),
            httpx.Response(200, json=tool_reply({"ok": True, "note": "n"})),
        ]
    )

    await client.complete_json("coach", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict)

    sent = json.loads(route.calls.last.request.read())["messages"]
    assert all(m["content"] for m in sent), "the API rejects a turn with no content"
    assert sent[-1]["role"] == "user"


@respx.mock
async def test_thinking_is_left_to_the_model_unless_switched_off(client: LLMClient):
    route = respx.post(API_URL).respond(json={"content": [{"type": "text", "text": "ok"}]})

    await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES)

    assert "thinking" not in json.loads(route.calls.last.request.read())


@respx.mock
async def test_a_short_reply_can_switch_thinking_off(client: LLMClient):
    route = respx.post(API_URL).respond(json={"content": [{"type": "text", "text": "ok"}]})

    await client.complete_text("x", model="m", system=SYSTEM, messages=MESSAGES, think=False)

    assert json.loads(route.calls.last.request.read())["thinking"] == {"type": "disabled"}


@respx.mock
async def test_a_structured_reply_can_switch_thinking_off(client: LLMClient):
    route = respx.post(API_URL).respond(json=tool_reply({"ok": True, "note": "fine"}))

    await client.complete_json(
        "x", model="m", system=SYSTEM, messages=MESSAGES, schema=Verdict, think=False
    )

    assert json.loads(route.calls.last.request.read())["thinking"] == {"type": "disabled"}


@respx.mock
async def test_a_reply_cut_off_before_any_text_is_an_error_not_silence(client: LLMClient):
    # A model that spends the whole budget thinking returns no text block at all.
    respx.post(API_URL).respond(
        json={
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "hmm"}],
            "usage": USAGE,
        }
    )

    with pytest.raises(LLMError, match="cut off"):
        await client.complete_text("child", model="m", system=SYSTEM, messages=MESSAGES)


@respx.mock
async def test_a_short_but_complete_reply_is_not_an_error(client: LLMClient):
    respx.post(API_URL).respond(
        json={
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "Half a sentence"}],
            "usage": USAGE,
        }
    )

    text = await client.complete_text("child", model="m", system=SYSTEM, messages=MESSAGES)

    assert text == "Half a sentence"


def test_cost_uses_tier_and_cache_discounts():
    haiku = estimate_cost("claude-haiku-5-5", 1_000_000, 0, 0, 0)
    assert haiku == Decimal("0.100000")
    assert estimate_cost("claude-haiku-5-5", 0, 1_000_000, 0, 0) == Decimal("0.500000")
    assert estimate_cost("claude-haiku-5-5", 0, 0, 1_000_000, 0) == Decimal("0.010000")
    assert estimate_cost("claude-haiku-5-5", 0, 0, 0, 1_000_000) == Decimal("0.125000")


@pytest.mark.parametrize(
    ("model", "per_million_in", "per_million_out"),
    [
        ("claude-haiku-5-5", "0.10", "0.50"),
        ("claude-sonnet-5-5", "2", "10"),
        ("claude-opus-5-5", "4", "20"),
        ("claude-haiku-4-5", "1", "5"),
    ],
)
def test_each_model_generation_is_priced_at_its_own_rate(
    model: str, per_million_in: str, per_million_out: str
):
    assert estimate_cost(model, 1_000_000, 0, 0, 0) == Decimal(per_million_in).quantize(
        Decimal("0.000001")
    )
    assert estimate_cost(model, 0, 1_000_000, 0, 0) == Decimal(per_million_out).quantize(
        Decimal("0.000001")
    )


def test_unknown_model_is_priced_as_sonnet():
    assert estimate_cost("mystery", 1_000_000, 0, 0, 0) == Decimal("3.000000")
