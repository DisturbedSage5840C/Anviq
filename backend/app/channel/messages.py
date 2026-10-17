"""Inbound WhatsApp message parsing. Boundary code: never trust the payload shape."""

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class InboundKind(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    BUTTON = "button"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class InboundMessage:
    wa_message_id: str
    sender_wa_id: str
    kind: InboundKind
    timestamp: int
    text: str | None = None
    media_id: str | None = None
    mime_type: str | None = None
    button_id: str | None = None

    def to_envelope(self) -> dict[str, Any]:
        """JSON-safe form for the job queue (contains the sender id, so never log it)."""
        return {
            "wa_message_id": self.wa_message_id,
            "sender_wa_id": self.sender_wa_id,
            "kind": self.kind.value,
            "timestamp": self.timestamp,
            "text": self.text,
            "media_id": self.media_id,
            "mime_type": self.mime_type,
            "button_id": self.button_id,
        }

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> "InboundMessage":
        return cls(
            wa_message_id=envelope["wa_message_id"],
            sender_wa_id=envelope["sender_wa_id"],
            kind=InboundKind(envelope["kind"]),
            timestamp=int(envelope["timestamp"]),
            text=envelope.get("text"),
            media_id=envelope.get("media_id"),
            mime_type=envelope.get("mime_type"),
            button_id=envelope.get("button_id"),
        )


def parse_inbound(payload: Mapping[str, Any]) -> list[InboundMessage]:
    """Extract messages from a webhook delivery; status receipts and junk yield nothing."""
    messages: list[InboundMessage] = []
    skipped = 0
    for raw in _iter_raw_messages(payload):
        parsed = _parse_one(raw)
        if parsed is None:
            skipped += 1
            continue
        messages.append(parsed)
    if skipped:
        logger.warning("skipped malformed whatsapp messages", extra={"count": skipped})
    return messages


def _iter_raw_messages(payload: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for entry in _as_list(payload.get("entry")):
        for change in _as_list(_as_dict(entry).get("changes")):
            value = _as_dict(_as_dict(change).get("value"))
            for raw in _as_list(value.get("messages")):
                if isinstance(raw, dict):
                    yield raw


def _parse_one(raw: Mapping[str, Any]) -> InboundMessage | None:
    message_id, sender = raw.get("id"), raw.get("from")
    if not isinstance(message_id, str) or not isinstance(sender, str):
        return None
    timestamp = _to_int(raw.get("timestamp"))

    def build(kind: InboundKind, **fields: str | None) -> InboundMessage:
        return InboundMessage(message_id, sender, kind, timestamp, **fields)

    kind = raw.get("type")
    if kind == "text":
        body = _as_dict(raw.get("text")).get("body")
        return build(InboundKind.TEXT, text=body if isinstance(body, str) else "")
    if kind == "audio":
        audio = _as_dict(raw.get("audio"))
        media_id, mime = audio.get("id"), audio.get("mime_type")
        if not isinstance(media_id, str):
            return None
        return build(
            InboundKind.AUDIO, media_id=media_id, mime_type=mime if isinstance(mime, str) else None
        )
    if kind == "interactive":
        interactive = _as_dict(raw.get("interactive"))
        reply = _as_dict(interactive.get("button_reply") or interactive.get("list_reply"))
        button_id, title = reply.get("id"), reply.get("title")
        if not isinstance(button_id, str):
            return None
        return build(
            InboundKind.BUTTON, button_id=button_id, text=title if isinstance(title, str) else None
        )
    return build(InboundKind.UNSUPPORTED)


def _as_dict(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _to_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
