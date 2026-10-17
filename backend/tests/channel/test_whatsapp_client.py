import json

import httpx
import pytest
import respx

from app.channel.whatsapp_client import (
    MAX_MEDIA_BYTES,
    OGG_OPUS_MIME,
    MediaTooLargeError,
    WhatsAppClient,
    WhatsAppError,
)

BASE = "https://graph.test/v25.0"
TOKEN = "tok-123"


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as http:
        yield WhatsAppClient(
            http, phone_number_id="555", access_token=TOKEN, base_url=BASE, retry_delay_s=0
        )


@respx.mock
async def test_send_text_posts_expected_body_and_returns_message_id(client) -> None:
    route = respx.post(f"{BASE}/555/messages").respond(json={"messages": [{"id": "wamid.out"}]})

    message_id = await client.send_text("919800000001", "नमस्ते")

    assert message_id == "wamid.out"
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919800000001",
        "type": "text",
        "text": {"body": "नमस्ते", "preview_url": False},
    }


@respx.mock
async def test_send_audio_marks_message_as_voice(client) -> None:
    route = respx.post(f"{BASE}/555/messages").respond(json={"messages": [{"id": "wamid.a"}]})

    await client.send_audio("919800000001", "media-1")

    body = json.loads(route.calls.last.request.content)
    assert body["type"] == "audio"
    assert body["audio"] == {"id": "media-1", "voice": True}


@respx.mock
async def test_upload_media_returns_id_and_sends_opus_mime(client) -> None:
    route = respx.post(f"{BASE}/555/media").respond(json={"id": "media-77"})

    media_id = await client.upload_media(b"OggS...", OGG_OPUS_MIME)

    assert media_id == "media-77"
    content = route.calls.last.request.content
    assert b"audio/ogg; codecs=opus" in content
    assert b'name="messaging_product"' in content


@respx.mock
async def test_send_buttons_builds_reply_buttons(client) -> None:
    route = respx.post(f"{BASE}/555/messages").respond(json={"messages": [{"id": "w"}]})

    await client.send_buttons("1", "Language?", [("lang_hi", "हिंदी"), ("lang_en", "English")])

    interactive = json.loads(route.calls.last.request.content)["interactive"]
    assert interactive["type"] == "button"
    assert [b["reply"]["id"] for b in interactive["action"]["buttons"]] == ["lang_hi", "lang_en"]


@respx.mock
async def test_download_media_resolves_url_then_fetches_with_auth(client) -> None:
    respx.get(f"{BASE}/media-9").respond(
        json={"url": "https://cdn.test/file", "mime_type": "audio/ogg", "file_size": "3"}
    )
    download = respx.get("https://cdn.test/file").respond(content=b"abc")

    media = await client.download_media("media-9")

    assert media.data == b"abc"
    assert media.mime_type == "audio/ogg"
    assert download.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
async def test_download_rejects_declared_oversize_media_without_fetching(client) -> None:
    respx.get(f"{BASE}/big").respond(
        json={
            "url": "https://cdn.test/big",
            "mime_type": "audio/ogg",
            "file_size": str(MAX_MEDIA_BYTES + 1),
        }
    )
    fetch = respx.get("https://cdn.test/big").respond(content=b"x")

    with pytest.raises(MediaTooLargeError):
        await client.download_media("big")

    assert not fetch.called


@respx.mock
async def test_download_rejects_oversize_body_even_if_size_was_understated(client) -> None:
    respx.get(f"{BASE}/liar").respond(
        json={"url": "https://cdn.test/liar", "mime_type": "audio/ogg", "file_size": "10"}
    )
    respx.get("https://cdn.test/liar").respond(content=b"x" * (MAX_MEDIA_BYTES + 1))

    with pytest.raises(MediaTooLargeError):
        await client.download_media("liar")


@respx.mock
async def test_retries_server_errors_then_succeeds(client) -> None:
    route = respx.post(f"{BASE}/555/messages").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]}),
        ]
    )

    assert await client.send_text("1", "hi") == "wamid.ok"
    assert route.call_count == 2


@respx.mock
async def test_client_error_is_not_retried_and_hides_token(client) -> None:
    route = respx.post(f"{BASE}/555/messages").respond(
        400, json={"error": {"code": 131047, "message": "Re-engagement message"}}
    )

    with pytest.raises(WhatsAppError) as info:
        await client.send_text("1", "hi")

    assert route.call_count == 1
    assert "131047" in str(info.value)
    assert TOKEN not in str(info.value)
