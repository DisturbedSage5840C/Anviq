"""Error reporting that cannot leak: Sentry gets stack traces and ids, never teacher content.

Teachers speak and type about their classrooms, and a phone number is their identity, so every
event is rebuilt through the PII scrubber before it leaves the process. The SDK's own PII
switches stay off; the scrubber is the second lock, not the only one.
"""

from collections.abc import Mapping
from typing import Any, cast

import sentry_sdk
from pydantic import SecretStr

from app.guardrails.pii import scrub

REDACTED = "[redacted]"

# Request fields that carry what a visitor said or sent, never needed to debug a failure.
_REQUEST_CONTENT_KEYS = ("data", "cookies", "query_string")
_BREADCRUMB_CONTENT_KEYS = ("body",)
_CREDENTIAL_HEADERS = frozenset(
    {"authorization", "cookie", "x-demo-code", "x-hub-signature", "x-hub-signature-256"}
)
# Dropped wherever they appear: locals hold transcripts, `user` holds the sender id and IP.
_DROPPED_KEYS = frozenset({"vars", "user"})


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
        cleaned["data"] = _redact_keys(data, _BREADCRUMB_CONTENT_KEYS)
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


def _redact_keys(values: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: REDACTED if key in keys else value for key, value in values.items()}


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, Mapping):
        return {key: _clean(item) for key, item in value.items() if key not in _DROPPED_KEYS}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value
