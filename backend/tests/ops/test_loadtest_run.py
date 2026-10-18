import json
from collections import Counter

import httpx

from app.ops.loadtest import sign_body
from app.ops.loadtest_run import is_production_host, run_turns_web, run_turns_webhook
from tests.conftest import TEST_APP_SECRET

BASE = "http://staging.test"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE)


def _message(request: httpx.Request) -> dict:
    return json.loads(request.content)["entry"][0]["changes"][0]["value"]["messages"][0]


async def test_webhook_load_sends_every_teacher_every_turn_signed():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with _client(handler) as client:
        outcomes = await run_turns_webhook(
            client, secret=TEST_APP_SECRET, run="r1", teachers=3, turns=2, think_s=0.0
        )

    assert len(outcomes) == 6
    assert all(o.succeeded for o in outcomes)
    assert Counter(_message(r)["from"] for r in seen).most_common()[-1][1] == 2
    assert len({_message(r)["id"] for r in seen}) == 6
    for request in seen:
        assert request.url.path == "/webhook/whatsapp"
        assert request.headers["X-Hub-Signature-256"] == sign_body(request.content, TEST_APP_SECRET)


async def test_webhook_load_records_a_dropped_connection_as_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _client(handler) as client:
        outcomes = await run_turns_webhook(
            client, secret=TEST_APP_SECRET, run="r1", teachers=2, turns=1, think_s=0.0
        )

    assert [o.status for o in outcomes] == [None, None]
    assert not any(o.succeeded for o in outcomes)


async def test_webhook_load_records_the_status_it_was_given():
    async with _client(lambda request: httpx.Response(503)) as client:
        outcomes = await run_turns_webhook(
            client, secret=TEST_APP_SECRET, run="r1", teachers=1, turns=1, think_s=0.0
        )

    assert [o.status for o in outcomes] == [503]


async def test_web_load_uses_one_demo_code_per_teacher_and_sends_utf8_text():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "ok"})

    async with _client(handler) as client:
        outcomes = await run_turns_web(client, codes=["code-a", "code-b"], turns=2, think_s=0.0)

    assert len(outcomes) == 4
    assert Counter(r.headers["X-Demo-Code"] for r in seen) == {"code-a": 2, "code-b": 2}
    for request in seen:
        assert request.url.path == "/web/turn"
        assert request.headers["Content-Type"] == "text/plain; charset=utf-8"
        assert request.content.decode("utf-8").strip()


async def test_web_load_records_a_refused_code_as_a_failure():
    async with _client(lambda request: httpx.Response(401)) as client:
        outcomes = await run_turns_web(client, codes=["code-a"], turns=1, think_s=0.0)

    assert [o.succeeded for o in outcomes] == [False]


def test_production_hosts_are_recognised():
    assert is_production_host("https://anviq-prod.fly.dev")
    assert is_production_host("https://API.ANVIQ-PROD.example/")


def test_staging_and_local_hosts_are_not_production():
    assert not is_production_host("https://anviq-staging.fly.dev")
    assert not is_production_host("http://localhost:8080")
