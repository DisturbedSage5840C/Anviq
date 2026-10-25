"""Evolution API's `messages.upsert` webhook, mapped onto the channel's own InboundMessage.

Boundary code: the call carries our shared secret, but the JSON inside is WhatsApp-sourced, so
every field may be missing or odd and nothing is trusted.
"""

import logging
import re
from collections.abc import Iterator, Mapping
from typing import Any

from app.channel.messages import InboundKind, InboundMessage

logger = logging.getLogger(__name__)

NEW_MESSAGE_EVENT = "messages.upsert"
# A teacher's question is a few sentences; this only stops a pasted wall of text reaching the LLM.
MAX_TEXT_CHARS = 4000
# Disappearing-chat and view-once messages arrive as {"<wrapper>": {"message": {...real one...}}}.
_WRAPPER_KEYS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "documentWithCaptionMessage",
)
MAX_WRAPPER_DEPTH = 3
# Protocol traffic, not something a teacher said: answering it would send an unprompted reply.
_NON_MESSAGE_KEYS = frozenset(
    {"reactionMessage", "protocolMessage", "editedMessage", "senderKeyDistributionMessage"}
)
# Present beside real content too, so on its own it means there is no content.
_METADATA_KEYS = frozenset({"messageContextInfo"})
# A unix timestamp has 10 digits today; anything longer is not one, and `int()` on a huge string
# raises. A clock running a day ahead is tolerated, further than that is a bad value.
_MAX_TIMESTAMP_DIGITS = 12
_MAX_CLOCK_SKEW_S = 86_400
PHONE_JID_SUFFIX = "@s.whatsapp.net"
# WhatsApp's privacy ids; Evolution adds the real phone JID as `remoteJidAlt` when it knows it.
LID_JID_SUFFIX = "@lid"
# E.164 allows 15 digits. [0-9], not \d: \d would also accept Devanagari and other Unicode digits.
_PHONE_DIGITS = re.compile(r"[0-9]{7,15}")
# Baileys ids are hex; the id keys the dedupe claim and the job, so keep it plain and short.
_MESSAGE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def parse_evolution_inbound(payload: object, *, now: int) -> InboundMessage | None:
    """The first usable teacher message in one webhook call, or None.

    Events other than new messages, our own sends, groups, broadcasts and malformed items give
    None. `now` stands in when the message carries no usable timestamp.
    """
    if not isinstance(payload, Mapping) or _event_name(payload.get("event")) != NEW_MESSAGE_EVENT:
        return None
    for item in _items(payload.get("data")):
        message = _parse_item(item, now)
        if message is not None:
            return message
    return None


def _event_name(raw: object) -> str:
    """`MESSAGES_UPSERT` and `messages.upsert` are the same event, depending on the setup."""
    return raw.strip().lower().replace("_", ".") if isinstance(raw, str) else ""


def _items(data: object) -> Iterator[Mapping[str, Any]]:
    candidates = data if isinstance(data, list) else [data]
    return (item for item in candidates if isinstance(item, Mapping))


def _parse_item(item: Mapping[str, Any], now: int) -> InboundMessage | None:
    key = item.get("key")
    if not isinstance(key, Mapping) or key.get("fromMe"):
        return None
    message_id, sender = key.get("id"), _sender_digits(key)
    if not isinstance(message_id, str) or not _MESSAGE_ID.fullmatch(message_id) or sender is None:
        return None
    timestamp = _timestamp(item.get("messageTimestamp"), now)
    content = _unwrap(item.get("message"))
    text = _text(content)
    if text:
        capped = text[:MAX_TEXT_CHARS]
        return InboundMessage(message_id, sender, InboundKind.TEXT, timestamp, text=capped)
    audio = content.get("audioMessage")
    if isinstance(audio, Mapping):
        mime = audio.get("mimetype")
        return InboundMessage(
            message_id,
            sender,
            InboundKind.AUDIO,
            timestamp,
            media_id=message_id,
            mime_type=mime if isinstance(mime, str) and mime else None,
        )
    if _is_not_a_message(content):
        return None
    return InboundMessage(message_id, sender, InboundKind.UNSUPPORTED, timestamp)


def _unwrap(raw: object) -> Mapping[str, Any]:
    """The message inside any disappearing/view-once wrappers, to a bounded depth."""
    content: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    for _ in range(MAX_WRAPPER_DEPTH):
        inner = next(
            (
                wrapped["message"]
                for key in _WRAPPER_KEYS
                if isinstance(wrapped := content.get(key), Mapping)
                and isinstance(wrapped.get("message"), Mapping)
            ),
            None,
        )
        if inner is None:
            break
        content = inner
    return content


def _is_not_a_message(content: Mapping[str, Any]) -> bool:
    """True for an empty body or protocol traffic (reaction, edit, revoke, key exchange)."""
    kinds = set(content) - _METADATA_KEYS
    return not kinds or bool(kinds & _NON_MESSAGE_KEYS)


def _text(content: Mapping[str, Any]) -> str:
    plain = content.get("conversation")
    if isinstance(plain, str) and plain:
        return plain
    extended = content.get("extendedTextMessage")
    quoted = extended.get("text") if isinstance(extended, Mapping) else None
    return quoted if isinstance(quoted, str) else ""


def _sender_digits(key: Mapping[str, Any]) -> str | None:
    jid = key.get("remoteJid")
    if isinstance(jid, str) and jid.endswith(LID_JID_SUFFIX):
        jid = key.get("remoteJidAlt")
        if not isinstance(jid, str):
            # No id in the log line: it is the sender's identity.
            logger.info("evolution message dropped: LID sender with no phone number")
    if not isinstance(jid, str) or not jid.endswith(PHONE_JID_SUFFIX):
        return None
    # A linked device adds ":<device>" before the "@".
    digits = jid.removesuffix(PHONE_JID_SUFFIX).split(":", 1)[0]
    return digits if _PHONE_DIGITS.fullmatch(digits) else None


def _timestamp(raw: object, now: int) -> int:
    seconds = _seconds(raw)
    return seconds if 0 < seconds <= now + _MAX_CLOCK_SKEW_S else now


def _seconds(raw: object) -> int:
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isascii() and raw.isdigit():
        return int(raw) if len(raw) <= _MAX_TIMESTAMP_DIGITS else 0
    return 0
