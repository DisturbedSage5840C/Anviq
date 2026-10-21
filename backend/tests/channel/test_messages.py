from app.channel.messages import InboundKind, failed_delivery_codes, parse_inbound


def _envelope(message: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": "1", "changes": [{"field": "messages", "value": {"messages": [message]}}]}
        ],
    }


def test_parses_text_message() -> None:
    payload = _envelope(
        {
            "id": "wamid.1",
            "from": "919800000001",
            "timestamp": "1700000000",
            "type": "text",
            "text": {"body": "Namaste"},
        }
    )

    [message] = parse_inbound(payload)

    assert message.kind is InboundKind.TEXT
    assert message.text == "Namaste"
    assert message.wa_message_id == "wamid.1"
    assert message.sender_wa_id == "919800000001"


def test_parses_audio_message_with_media_id() -> None:
    payload = _envelope(
        {
            "id": "wamid.2",
            "from": "919800000001",
            "timestamp": "1700000001",
            "type": "audio",
            "audio": {"id": "media-9", "mime_type": "audio/ogg; codecs=opus", "voice": True},
        }
    )

    [message] = parse_inbound(payload)

    assert message.kind is InboundKind.AUDIO
    assert message.media_id == "media-9"
    assert message.mime_type == "audio/ogg; codecs=opus"
    assert message.text is None


def test_parses_interactive_button_reply() -> None:
    payload = _envelope(
        {
            "id": "wamid.3",
            "from": "919800000001",
            "timestamp": "1700000002",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "lang_hi", "title": "हिंदी"},
            },
        }
    )

    [message] = parse_inbound(payload)

    assert message.kind is InboundKind.BUTTON
    assert message.button_id == "lang_hi"
    assert message.text == "हिंदी"


def test_image_is_marked_unsupported() -> None:
    payload = _envelope(
        {
            "id": "wamid.4",
            "from": "919800000001",
            "timestamp": "1700000003",
            "type": "image",
            "image": {"id": "x"},
        }
    )

    [message] = parse_inbound(payload)

    assert message.kind is InboundKind.UNSUPPORTED


def test_status_only_payload_yields_no_messages() -> None:
    payload = {
        "entry": [
            {"changes": [{"value": {"statuses": [{"id": "wamid.1", "status": "delivered"}]}}]}
        ]
    }

    assert parse_inbound(payload) == []


def test_malformed_payload_yields_no_messages() -> None:
    assert parse_inbound({"entry": "nope"}) == []
    assert parse_inbound({}) == []
    assert parse_inbound({"entry": [{"changes": [{"value": {"messages": [{"id": 5}]}}]}]}) == []


def test_multiple_messages_in_one_delivery_keep_order() -> None:
    first = {"id": "a", "from": "1", "timestamp": "1", "type": "text", "text": {"body": "x"}}
    second = {"id": "b", "from": "1", "timestamp": "2", "type": "text", "text": {"body": "y"}}
    payload = {"entry": [{"changes": [{"value": {"messages": [first, second]}}]}]}

    assert [m.wa_message_id for m in parse_inbound(payload)] == ["a", "b"]


def _status_payload(*statuses: dict) -> dict:
    return {"entry": [{"changes": [{"value": {"statuses": list(statuses)}}]}]}


def test_a_failed_delivery_status_yields_its_error_code() -> None:
    payload = _status_payload(
        {
            "id": "wamid.9",
            "recipient_id": "919800000001",
            "status": "failed",
            "errors": [{"code": 131030, "title": "Recipient not in allowed list"}],
        }
    )

    assert failed_delivery_codes(payload) == [131030]


def test_delivered_and_read_statuses_are_not_failures() -> None:
    payload = _status_payload({"status": "delivered"}, {"status": "read"}, {"status": "sent"})

    assert failed_delivery_codes(payload) == []


def test_a_failed_status_without_a_usable_code_is_reported_as_zero() -> None:
    payload = _status_payload({"status": "failed"}, {"status": "failed", "errors": ["nope"]})

    assert failed_delivery_codes(payload) == [0, 0]


def test_malformed_payload_yields_no_failed_codes() -> None:
    assert failed_delivery_codes({"entry": "nope"}) == []
    assert failed_delivery_codes({}) == []
