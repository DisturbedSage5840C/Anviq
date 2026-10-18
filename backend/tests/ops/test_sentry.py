"""Sentry must never receive a transcript, a phone number or a credential."""

from typing import Any

import pytest
import sentry_sdk
from pydantic import SecretStr

from app.ops import sentry as sentry_module
from app.ops.sentry import REDACTED, init_sentry, scrub_breadcrumb, scrub_event

PHONE = "919876543210"


def test_phone_numbers_in_an_exception_message_are_scrubbed():
    event = {"exception": {"values": [{"type": "ValueError", "value": f"bad sender {PHONE}"}]}}

    scrubbed = scrub_event(event, {})

    assert PHONE not in str(scrubbed)


def test_the_original_event_is_left_untouched():
    event = {"message": f"call {PHONE}"}

    scrub_event(event, {})

    assert event == {"message": f"call {PHONE}"}


def test_request_bodies_cookies_and_query_strings_are_dropped():
    event = {
        "request": {
            "url": "https://api.example/web/turn",
            "method": "POST",
            "data": "कल का प्लान",
            "cookies": {"sid": "x"},
            "query_string": f"phone={PHONE}",
        }
    }

    request = scrub_event(event, {})["request"]

    assert request == {
        "url": "https://api.example/web/turn",
        "method": "POST",
        "data": REDACTED,
        "cookies": REDACTED,
        "query_string": REDACTED,
    }


def test_credential_headers_are_redacted_and_harmless_ones_kept():
    event = {
        "request": {
            "headers": {
                "X-Demo-Code": "a" * 22,
                "Authorization": "Bearer secret",
                "X-Hub-Signature-256": "sha256=abc",
                "Content-Type": "audio/ogg",
            }
        }
    }

    headers = scrub_event(event, {})["request"]["headers"]

    assert headers == {
        "X-Demo-Code": REDACTED,
        "Authorization": REDACTED,
        "X-Hub-Signature-256": REDACTED,
        "Content-Type": "audio/ogg",
    }


def test_the_user_block_and_local_variables_are_removed():
    event = {
        "user": {"id": PHONE, "ip_address": "1.2.3.4"},
        "exception": {
            "values": [
                {"stacktrace": {"frames": [{"function": "f", "vars": {"text": "secret words"}}]}}
            ]
        },
    }

    scrubbed = scrub_event(event, {})

    assert "user" not in scrubbed
    assert scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0] == {"function": "f"}


def test_a_nested_extra_value_is_scrubbed_through_lists_too():
    event = {"extra": {"rows": [{"note": f"mail a@b.com or {PHONE}"}]}}

    text = str(scrub_event(event, {}))

    assert "a@b.com" not in text
    assert PHONE not in text


def test_breadcrumbs_are_scrubbed_and_http_bodies_dropped():
    crumb = {"message": f"sent to {PHONE}", "data": {"url": "https://x", "body": "words"}}

    scrubbed = scrub_breadcrumb(crumb, {})

    assert PHONE not in str(scrubbed)
    assert scrubbed["data"]["body"] == REDACTED


def test_without_a_dsn_sentry_is_not_started(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    assert init_sentry(None, environment="prod") is False
    assert calls == []


def test_with_a_dsn_sentry_starts_with_pii_off_and_the_scrubbers_wired(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    started = init_sentry(SecretStr("https://k@o0.ingest.sentry.io/1"), environment="staging")

    assert started is True
    options = calls[0]
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["environment"] == "staging"
    assert options["before_send"] is sentry_module.scrub_event
    assert options["before_breadcrumb"] is sentry_module.scrub_breadcrumb
