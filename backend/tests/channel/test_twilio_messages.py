import pytest

from app.channel.messages import InboundKind, InboundMessage
from app.channel.sender_key import sender_key
from app.channel.twilio_messages import parse_twilio_inbound

NOW = 1_792_000_000
MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1"


def _form(**overrides: str) -> dict[str, str]:
    base = {
        "MessageSid": "SM0123456789abcdef0123456789abcdef",
        "From": "whatsapp:+919800000001",
        "To": "whatsapp:+14155238886",
        "WaId": "919800000001",
        "ProfileName": "Asha",
        "Body": "नमस्ते",
        "NumMedia": "0",
    }
    return {**base, **overrides}


def test_a_text_message_becomes_a_text_inbound_message() -> None:
    message = parse_twilio_inbound(_form(), now=NOW)

    assert message == InboundMessage(
        wa_message_id="SM0123456789abcdef0123456789abcdef",
        sender_wa_id="919800000001",
        kind=InboundKind.TEXT,
        timestamp=NOW,
        text="नमस्ते",
    )


def test_the_sender_is_the_bare_digits_so_it_hashes_like_a_meta_sender(settings) -> None:
    twilio = parse_twilio_inbound(_form(), now=NOW)
    meta_style_id = "919800000001"

    assert twilio is not None
    assert sender_key(settings, twilio.sender_wa_id) == sender_key(settings, meta_style_id)


def test_the_sender_comes_from_the_from_field_so_wa_id_is_not_required() -> None:
    form = _form()
    del form["WaId"]

    message = parse_twilio_inbound(form, now=NOW)

    assert message is not None and message.sender_wa_id == "919800000001"


def test_a_voice_note_becomes_an_audio_message_carrying_its_media_url() -> None:
    form = _form(Body="", NumMedia="1", MediaUrl0=MEDIA_URL, MediaContentType0="audio/ogg")

    message = parse_twilio_inbound(form, now=NOW)

    assert message is not None
    assert message.kind is InboundKind.AUDIO
    assert (message.media_id, message.mime_type) == (MEDIA_URL, "audio/ogg")
    assert message.text is None


@pytest.mark.parametrize("content_type", ["image/jpeg", "application/pdf", "video/mp4", ""])
def test_other_media_is_unsupported(content_type: str) -> None:
    form = _form(Body="", NumMedia="1", MediaUrl0=MEDIA_URL, MediaContentType0=content_type)

    message = parse_twilio_inbound(form, now=NOW)

    assert message is not None and message.kind is InboundKind.UNSUPPORTED


def test_audio_without_a_media_url_is_unsupported() -> None:
    form = _form(Body="", NumMedia="1", MediaContentType0="audio/ogg")

    message = parse_twilio_inbound(form, now=NOW)

    assert message is not None and message.kind is InboundKind.UNSUPPORTED


def test_a_message_with_no_text_and_no_media_is_unsupported() -> None:
    message = parse_twilio_inbound(_form(Body="", Latitude="12.9", Longitude="77.5"), now=NOW)

    assert message is not None and message.kind is InboundKind.UNSUPPORTED


@pytest.mark.parametrize("num_media", ["", "x", "-1"])
def test_a_garbled_media_count_is_treated_as_text(num_media: str) -> None:
    message = parse_twilio_inbound(_form(NumMedia=num_media), now=NOW)

    assert message is not None and message.kind is InboundKind.TEXT


@pytest.mark.parametrize(
    "overrides",
    [
        {"MessageSid": ""},
        {"From": "whatsapp:+"},
        {"From": "sms:+919800000001"},
        {"From": "whatsapp:+not-digits"},
        {"From": "whatsapp:+" + "1" * 40},
        {"From": "whatsapp:+९८००००००००१"},
    ],
)
def test_a_form_without_a_usable_id_or_sender_yields_nothing(overrides: dict[str, str]) -> None:
    assert parse_twilio_inbound(_form(**overrides), now=NOW) is None


def test_a_missing_message_sid_yields_nothing() -> None:
    form = _form()
    del form["MessageSid"]

    assert parse_twilio_inbound(form, now=NOW) is None


def test_the_envelope_round_trips_through_the_job_queue() -> None:
    message = parse_twilio_inbound(_form(), now=NOW)

    assert message is not None
    assert InboundMessage.from_envelope(message.to_envelope()) == message


@pytest.mark.parametrize(
    "status", [{"MessageStatus": "delivered"}, {"SmsStatus": "sent"}, {"SmsStatus": "undelivered"}]
)
def test_a_delivery_status_callback_is_not_an_inbound_message(status: dict[str, str]) -> None:
    assert parse_twilio_inbound(_form(**status), now=NOW) is None


def test_an_inbound_message_marked_received_is_still_a_message() -> None:
    message = parse_twilio_inbound(_form(SmsStatus="received"), now=NOW)

    assert message is not None and message.text == "नमस्ते"
