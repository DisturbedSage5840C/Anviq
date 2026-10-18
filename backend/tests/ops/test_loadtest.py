import json

import pytest

from app.ops.loadtest import (
    LoadBudget,
    Outcome,
    check_budget,
    fake_sender,
    message_id,
    percentile,
    sign_body,
    summarise,
    webhook_body,
)
from tests.conftest import TEST_APP_SECRET, sign

URL = "/webhook/whatsapp"


def _ok(latency_s: float) -> Outcome:
    return Outcome(status=200, latency_s=latency_s)


def test_signature_matches_the_one_the_webhook_tests_use():
    body = b'{"a": 1}'

    assert sign_body(body, TEST_APP_SECRET) == sign(body)


def test_generated_webhook_body_is_accepted_by_the_real_webhook(client):
    body = webhook_body(sender="919999000001", wamid="wamid.run1.t1.m1", text="Namaste")

    response = client.post(
        URL, content=body, headers={"X-Hub-Signature-256": sign_body(body, TEST_APP_SECRET)}
    )

    assert response.status_code == 200


def test_webhook_body_carries_the_sender_id_and_text():
    payload = json.loads(webhook_body(sender="919999000007", wamid="wamid.x", text="hello"))

    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert (message["from"], message["id"], message["text"]["body"]) == (
        "919999000007",
        "wamid.x",
        "hello",
    )


def test_fake_senders_are_distinct_twelve_digit_numbers():
    senders = {fake_sender(i) for i in range(50)}

    assert len(senders) == 50
    assert all(len(s) == 12 and s.isdigit() for s in senders)


def test_message_ids_differ_between_runs_so_dedupe_cannot_hide_a_rerun():
    first = message_id(run="aaaa", teacher=3, turn=1)
    second = message_id(run="bbbb", teacher=3, turn=1)

    assert first != second


def test_message_ids_differ_between_teachers_and_turns():
    ids = {message_id(run="r", teacher=t, turn=n) for t in range(5) for n in range(5)}

    assert len(ids) == 25


def test_percentile_uses_nearest_rank():
    values = [float(n) for n in range(1, 101)]

    assert (percentile(values, 50), percentile(values, 95), percentile(values, 100)) == (
        50.0,
        95.0,
        100.0,
    )


def test_percentile_of_one_value_is_that_value():
    assert percentile([2.5], 95) == 2.5


def test_percentile_rejects_an_empty_sample():
    with pytest.raises(ValueError, match="no samples"):
        percentile([], 95)


def test_summary_counts_failures_and_transport_errors():
    outcomes = [_ok(0.1), _ok(0.2), Outcome(status=503, latency_s=0.05), Outcome(None, 5.0)]

    summary = summarise(outcomes, wall_s=2.0)

    assert (summary.requests, summary.ok, summary.failed) == (4, 2, 2)
    assert summary.error_rate == 0.5
    assert summary.requests_per_s == 2.0


def test_summary_latency_ignores_failed_requests():
    outcomes = [_ok(1.0), _ok(2.0), Outcome(status=401, latency_s=0.001)]

    summary = summarise(outcomes, wall_s=1.0)

    assert (summary.p50_s, summary.max_s) == (1.0, 2.0)


def test_summary_with_no_successes_has_no_latency_but_full_error_rate():
    summary = summarise([Outcome(None, 3.0), Outcome(500, 0.2)], wall_s=1.0)

    assert (summary.ok, summary.error_rate, summary.p95_s) == (0, 1.0, 0.0)


def test_summary_rejects_a_run_with_no_requests():
    with pytest.raises(ValueError, match="no requests"):
        summarise([], wall_s=1.0)


def test_budget_passes_when_every_limit_holds():
    summary = summarise([_ok(0.1)] * 20, wall_s=1.0)

    assert check_budget(summary, LoadBudget(p50_s=1.0, p95_s=2.0, max_error_rate=0.01)) == []


def test_budget_names_each_limit_that_is_broken():
    outcomes = [_ok(3.0)] * 18 + [Outcome(500, 0.1)] * 2
    summary = summarise(outcomes, wall_s=1.0)

    problems = check_budget(summary, LoadBudget(p50_s=1.0, p95_s=2.0, max_error_rate=0.01))

    assert len(problems) == 3
    assert any("p50" in p for p in problems)
    assert any("p95" in p for p in problems)
    assert any("error rate" in p for p in problems)
