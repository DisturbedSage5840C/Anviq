"""Error reporting that cannot leak: Sentry gets stack traces and ids, never teacher content.

Teachers speak and type about their classrooms, and a phone number is their identity, so every
event is rebuilt through the PII scrubber before it leaves the process. The SDK's own PII
switches stay off; the scrubber is the second lock, not the only one.
"""

import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

import sentry_sdk
from pydantic import SecretStr

from app.guardrails.pii import scrub

REDACTED = "[redacted]"
PHONE_REDACTED = "[phone]"

# Request fields that carry what a visitor said or sent, never needed to debug a failure.
_REQUEST_CONTENT_KEYS = ("data", "cookies", "query_string")
_BREADCRUMB_CONTENT_KEYS = ("body",)
_CREDENTIAL_HEADERS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "x-anviq-webhook-secret",
        "x-demo-code",
        "x-hub-signature",
        "x-hub-signature-256",
        "x-twilio-signature",
    }
)
# Dropped wherever they appear: locals hold transcripts, `user` holds the sender id and IP.
_DROPPED_KEYS = frozenset({"vars", "user"})
# The ops webhook URL is a credential, so an outgoing request keeps its host and nothing else.
_BREADCRUMB_URL_KEY = "url"
_BREADCRUMB_URL_PARTS_DROPPED = ("http.query", "http.fragment")
# Any 10 to 15 digit run, with an optional +: a phone or WhatsApp id in any country format.
_LONG_NUMBER = re.compile(r"(?<!\w)\+?\d{10,15}(?!\w)")


def scrub_event(event: Mapping[str, Any], hint: Mapping[str, Any]) -> dict[str, Any]:
    """Sentry `before_send`: a scrubbed copy of the event, the original left untouched."""
    cleaned: dict[str, Any] = _clean(event)
    request = cleaned.get("request")
    if isinstance(request, dict):
        cleaned["request"] = _scrub_request(request)
    return cleaned


def scrub_breadcrumb(crumb: Mapping[str, Any], hint: Mapping[str, Any]) -> dict[str, Any]:
    """Sentry `before_breadcrumb`: breadcrumbs record log lines and HTTP calls."""
    cleaned: dict[str, Any] = _clean(crumb)
    data = cleaned.get("data")
    if isinstance(data, dict):
        cleaned["data"] = _scrub_breadcrumb_data(data)
    return cleaned


def init_sentry(dsn: SecretStr | None, *, environment: str) -> bool:
    """Start error reporting if a DSN is configured. Returns whether it started."""
    if dsn is None:
        return False
    sentry_sdk.init(
        dsn=dsn.get_secret_value(),
        environment=environment,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
        # The SDK types events as a TypedDict; the scrubber works on plain mappings.
        before_send=cast(Any, scrub_event),
        before_breadcrumb=cast(Any, scrub_breadcrumb),
    )
    return True


def _scrub_request(request: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_keys(request, _REQUEST_CONTENT_KEYS)
    headers = redacted.get("headers")
    if isinstance(headers, dict):
        redacted["headers"] = {
            name: REDACTED if name.lower() in _CREDENTIAL_HEADERS else value
            for name, value in headers.items()
        }
    return redacted


def _scrub_breadcrumb_data(data: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_keys(data, _BREADCRUMB_CONTENT_KEYS)
    for key in _BREADCRUMB_URL_PARTS_DROPPED:
        redacted.pop(key, None)
    if _BREADCRUMB_URL_KEY in redacted:
        redacted[_BREADCRUMB_URL_KEY] = _host_only(redacted[_BREADCRUMB_URL_KEY])
    return redacted


def _host_only(url: Any) -> str:
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or not parts.scheme or not parts.hostname:
        return REDACTED
    return f"{parts.scheme}://{parts.hostname}"


def _redact_keys(values: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: REDACTED if key in keys else value for key, value in values.items()}


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return _LONG_NUMBER.sub(PHONE_REDACTED, scrub(value))
    if isinstance(value, Mapping):
        return {key: _clean(item) for key, item in value.items() if key not in _DROPPED_KEYS}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value
