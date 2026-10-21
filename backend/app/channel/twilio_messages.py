"""Twilio's WhatsApp inbound form, mapped onto the channel's own InboundMessage.

Boundary code: the form is signed, but a field can still be missing or odd, so nothing is trusted.
"""

import re
from collections.abc import Mapping
from dataclasses import replace

from app.channel.messages import InboundKind, InboundMessage

WHATSAPP_PREFIX = "whatsapp:+"
AUDIO_MIME_PREFIX = "audio/"
INBOUND_SMS_STATUS = "received"
# E.164 allows 15 digits. [0-9], not \d: \d would also accept Devanagari and other Unicode digits.
_PHONE_DIGITS = re.compile(r"[0-9]{7,15}")


def parse_twilio_inbound(form: Mapping[str, str], *, now: int) -> InboundMessage | None:
    """The message in one Twilio webhook form, or None if it has no usable id or sender.

    Twilio sends no message timestamp, so the caller supplies the receipt time. The sender is
    the bare digits of `From`, the same shape Meta uses, so one teacher hashes the same way
    on either provider.
    """
    if _is_status_callback(form):
        return None
    message_id = form.get("MessageSid", "")
    sender = _sender_digits(form.get("From", ""))
    if not message_id or sender is None:
        return None
    unsupported = InboundMessage(message_id, sender, InboundKind.UNSUPPORTED, now)
    if _media_count(form.get("NumMedia", "")) > 0:
        return _media_message(form, unsupported)
    body = form.get("Body", "")
    return replace(unsupported, kind=InboundKind.TEXT, text=body) if body else unsupported


def _is_status_callback(form: Mapping[str, str]) -> bool:
    """Delivery receipts can reach this URL too; they carry a sid and From but no teacher text."""
    if "MessageStatus" in form:
        return True
    return "SmsStatus" in form and form["SmsStatus"] != INBOUND_SMS_STATUS


def _media_message(form: Mapping[str, str], unsupported: InboundMessage) -> InboundMessage:
    """Voice notes are audio; any other attachment is not something the pipeline can use."""
    url, mime = form.get("MediaUrl0", ""), form.get("MediaContentType0", "")
    is_audio = mime.split(";")[0].strip().lower().startswith(AUDIO_MIME_PREFIX)
    if not (url and is_audio):
        return unsupported
    return replace(unsupported, kind=InboundKind.AUDIO, media_id=url, mime_type=mime)


def _sender_digits(from_field: str) -> str | None:
    if not from_field.startswith(WHATSAPP_PREFIX):
        return None
    digits = from_field.removeprefix(WHATSAPP_PREFIX)
    return digits if _PHONE_DIGITS.fullmatch(digits) else None


def _media_count(raw: str) -> int:
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0
