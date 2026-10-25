import logging
from typing import Any

import pytest

from app.channel.evolution_messages import MAX_TEXT_CHARS, parse_evolution_inbound
from app.channel.messages import InboundKind

NOW = 1_800_000_000
SENDER = "919800000001"
MESSAGE_ID = "3EB0A1B2C3D4E5F6"


def _payload(
    message: dict[str, Any] | None = None,
    *,
    event: str = "messages.upsert",
    key: dict[str, Any] | None = None,
    timestamp: Any = 1_799_999_990,
) -> dict[str, Any]:
    return {
        "event": event,
        "instance": "anviq-demo",
        "data": {
            "key": {
                "remoteJid": f"{SENDER}@s.whatsapp.net",
                "fromMe": False,
                "id": MESSAGE_ID,
                **(key or {}),
            },
            "pushName": "Teacher",
            "message": message if message is not None else {"conversation": "hello"},
            "messageType": "conversation",
            "messageTimestamp": timestamp,
        },
    }


def test_a_plain_text_message_becomes_a_text_message() -> None:
    message = parse_evolution_inbound(_payload({"conversation": "How do I teach sounds?"}), now=NOW)

    assert message is not None
    assert (message.kind, message.sender_wa_id) == (InboundKind.TEXT, SENDER)
    assert (message.wa_message_id, message.text) == (MESSAGE_ID, "How do I teach sounds?")
    assert message.timestamp == 1_799_999_990


def test_an_extended_text_message_such_as_a_reply_is_read_as_text() -> None:
    body = {"extendedTextMessage": {"text": "a quoted reply"}}

    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None and message.text == "a quoted reply"


def test_a_voice_note_becomes_audio_with_the_message_id_as_its_media_id() -> None:
    body = {"audioMessage": {"mimetype": "audio/ogg; codecs=opus", "ptt": True, "seconds": 7}}

    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None
    assert message.kind == InboundKind.AUDIO
    assert message.media_id == MESSAGE_ID
    assert message.mime_type == "audio/ogg; codecs=opus"


def test_an_audio_message_without_a_mimetype_still_parses_as_audio() -> None:
    message = parse_evolution_inbound(_payload({"audioMessage": {}}), now=NOW)

    assert message is not None
    assert (message.kind, message.mime_type) == (InboundKind.AUDIO, None)


@pytest.mark.parametrize(
    "body",
    [
        {"imageMessage": {"mimetype": "image/jpeg"}},
        {"stickerMessage": {}},
        {"documentMessage": {}},
        {"locationMessage": {}},
    ],
)
def test_other_attachments_are_unsupported_but_still_carry_the_sender(body: dict[str, Any]) -> None:
    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None
    assert (message.kind, message.sender_wa_id) == (InboundKind.UNSUPPORTED, SENDER)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"messageContextInfo": {"deviceListMetadata": {}}},
        {"reactionMessage": {"text": "👍"}},
        {"protocolMessage": {"type": "REVOKE"}},
        {"editedMessage": {"message": {"conversation": "fixed typo"}}},
        {"senderKeyDistributionMessage": {"groupId": "x"}},
        {"senderKeyDistributionMessage": {}, "messageContextInfo": {}},
    ],
)
def test_events_that_are_not_a_teacher_message_get_no_reply(body: dict[str, Any]) -> None:
    assert parse_evolution_inbound(_payload(body), now=NOW) is None


@pytest.mark.parametrize(
    "wrapper",
    ["ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "viewOnceMessageV2Extension"],
)
def test_a_text_inside_a_disappearing_or_view_once_wrapper_is_read_as_text(wrapper: str) -> None:
    body = {wrapper: {"message": {"conversation": "wrapped hello"}}}

    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None
    assert (message.kind, message.text) == (InboundKind.TEXT, "wrapped hello")


def test_a_voice_note_inside_an_ephemeral_wrapper_is_still_audio() -> None:
    body = {"ephemeralMessage": {"message": {"audioMessage": {"mimetype": "audio/ogg"}}}}

    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None
    assert (message.kind, message.media_id) == (InboundKind.AUDIO, MESSAGE_ID)


def test_an_image_inside_a_wrapper_is_unsupported() -> None:
    body = {"viewOnceMessage": {"message": {"imageMessage": {}}}}

    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None and message.kind == InboundKind.UNSUPPORTED


def test_a_reaction_inside_a_wrapper_gets_no_reply() -> None:
    body = {"ephemeralMessage": {"message": {"reactionMessage": {"text": "👍"}}}}

    assert parse_evolution_inbound(_payload(body), now=NOW) is None


def test_wrappers_nested_beyond_the_depth_limit_are_not_followed() -> None:
    body: dict[str, Any] = {"conversation": "too deep"}
    for _ in range(10):
        body = {"ephemeralMessage": {"message": body}}

    message = parse_evolution_inbound(_payload(body), now=NOW)

    assert message is not None and message.kind == InboundKind.UNSUPPORTED


def test_text_beyond_the_length_cap_is_truncated() -> None:
    message = parse_evolution_inbound(_payload({"conversation": "a" * 10_000}), now=NOW)

    assert message is not None and message.text == "a" * MAX_TEXT_CHARS


def test_an_empty_text_body_is_unsupported() -> None:
    message = parse_evolution_inbound(_payload({"conversation": ""}), now=NOW)

    assert message is not None and message.kind == InboundKind.UNSUPPORTED


@pytest.mark.parametrize("event", ["MESSAGES_UPSERT", "messages.upsert", "Messages.Upsert"])
def test_the_event_name_is_matched_whatever_its_spelling(event: str) -> None:
    assert parse_evolution_inbound(_payload(event=event), now=NOW) is not None


@pytest.mark.parametrize(
    "event", ["messages.update", "connection.update", "qrcode.updated", "send.message", ""]
)
def test_events_other_than_new_messages_are_ignored(event: str) -> None:
    assert parse_evolution_inbound(_payload(event=event), now=NOW) is None


def test_the_bots_own_messages_are_ignored_so_it_never_answers_itself() -> None:
    assert parse_evolution_inbound(_payload(key={"fromMe": True}), now=NOW) is None


@pytest.mark.parametrize(
    "jid",
    ["120363000000000000@g.us", "status@broadcast", "919800000001@broadcast", "abc@s.whatsapp.net"],
)
def test_groups_broadcasts_and_odd_jids_are_ignored(jid: str) -> None:
    assert parse_evolution_inbound(_payload(key={"remoteJid": jid}), now=NOW) is None


def test_a_lid_jid_uses_the_phone_number_from_remote_jid_alt() -> None:
    key = {"remoteJid": "12345678901234@lid", "remoteJidAlt": f"{SENDER}@s.whatsapp.net"}

    message = parse_evolution_inbound(_payload(key=key), now=NOW)

    assert message is not None and message.sender_wa_id == SENDER


def test_a_lid_jid_with_no_phone_number_is_ignored() -> None:
    assert (
        parse_evolution_inbound(_payload(key={"remoteJid": "12345678901234@lid"}), now=NOW) is None
    )


def test_a_dropped_lid_sender_is_logged_without_the_id(caplog: pytest.LogCaptureFixture) -> None:
    lid = "12345678901234"

    with caplog.at_level(logging.INFO, logger="app.channel.evolution_messages"):
        parse_evolution_inbound(_payload(key={"remoteJid": f"{lid}@lid"}), now=NOW)

    assert "LID" in caplog.text
    assert lid not in caplog.text


def test_a_device_suffix_on_the_jid_is_dropped() -> None:
    key = {"remoteJid": f"{SENDER}:12@s.whatsapp.net"}

    message = parse_evolution_inbound(_payload(key=key), now=NOW)

    assert message is not None and message.sender_wa_id == SENDER


def test_a_missing_message_id_is_ignored() -> None:
    assert parse_evolution_inbound(_payload(key={"id": ""}), now=NOW) is None


@pytest.mark.parametrize("timestamp", [None, "soon", -5, True])
def test_a_bad_timestamp_falls_back_to_the_receipt_time(timestamp: Any) -> None:
    message = parse_evolution_inbound(_payload(timestamp=timestamp), now=NOW)

    assert message is not None and message.timestamp == NOW


@pytest.mark.parametrize(
    "timestamp",
    ["9" * 5000, "9" * 13, NOW + 86_401, str(NOW + 10**6), 10**30],
)
def test_an_absurd_or_far_future_timestamp_falls_back_to_the_receipt_time(timestamp: Any) -> None:
    message = parse_evolution_inbound(_payload(timestamp=timestamp), now=NOW)

    assert message is not None and message.timestamp == NOW


def test_a_timestamp_a_little_ahead_of_our_clock_is_kept() -> None:
    message = parse_evolution_inbound(_payload(timestamp=NOW + 60), now=NOW)

    assert message is not None and message.timestamp == NOW + 60


def test_a_numeric_string_timestamp_is_accepted() -> None:
    message = parse_evolution_inbound(_payload(timestamp="1799999000"), now=NOW)

    assert message is not None and message.timestamp == 1_799_999_000


def test_data_sent_as_a_list_uses_its_first_usable_message() -> None:
    payload = _payload()
    payload["data"] = [{"key": {"remoteJid": "x@g.us", "id": "G1"}}, payload["data"]]

    message = parse_evolution_inbound(payload, now=NOW)

    assert message is not None and message.wa_message_id == MESSAGE_ID


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"event": "messages.upsert"},
        {"event": "messages.upsert", "data": None},
        {"event": "messages.upsert", "data": "text"},
        {"event": "messages.upsert", "data": {"key": "oops"}},
        {"event": "messages.upsert", "data": {"key": {}, "message": []}},
        {"event": 5, "data": {}},
    ],
)
def test_malformed_payloads_yield_nothing_instead_of_raising(payload: dict[str, Any]) -> None:
    assert parse_evolution_inbound(payload, now=NOW) is None
