import base64
import json
import logging

import httpx
import pytest
import respx

from app.channel.evolution_client import EvolutionWhatsAppClient
from app.channel.whatsapp_client import (
    MAX_MEDIA_BYTES,
    DownloadedMedia,
    MediaTooLargeError,
    WhatsAppError,
)

BASE = "http://evolution.test:8080"
API_KEY = "super-secret-evolution-key"
INSTANCE = "anviq-demo"
SEND_TEXT_URL = f"{BASE}/message/sendText/{INSTANCE}"
SEND_AUDIO_URL = f"{BASE}/message/sendWhatsAppAudio/{INSTANCE}"
MEDIA_URL = f"{BASE}/chat/getBase64FromMediaMessage/{INSTANCE}"
SENDER = "919800000001"
SENT = {"key": {"id": "3EB0SENT"}, "status": "PENDING"}


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as http:
        yield EvolutionWhatsAppClient(
            http, base_url=BASE, api_key=API_KEY, instance=INSTANCE, retry_delay_s=0
        )


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# --- text -------------------------------------------------------------------------------------


@respx.mock
async def test_send_text_posts_the_reply_with_the_api_key_and_returns_the_message_id(
    client: EvolutionWhatsAppClient,
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(return_value=httpx.Response(201, json=SENT))

    message_id = await client.send_text(SENDER, "नमस्ते शिक्षक")

    assert message_id == "3EB0SENT"
    request = route.calls.last.request
    assert request.headers["apikey"] == API_KEY
    assert _body(request) == {"number": SENDER, "text": "नमस्ते शिक्षक"}


@respx.mock
async def test_a_base_url_with_a_trailing_slash_still_reaches_the_right_path() -> None:
    route = respx.post(SEND_TEXT_URL).mock(return_value=httpx.Response(201, json=SENT))
    async with httpx.AsyncClient() as http:
        slashed = EvolutionWhatsAppClient(
            http, base_url=f"{BASE}/", api_key=API_KEY, instance=INSTANCE, retry_delay_s=0
        )

        await slashed.send_text(SENDER, "hi")

    assert route.called


@respx.mock
async def test_an_empty_reply_is_refused_before_anything_is_sent(
    client: EvolutionWhatsAppClient,
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(return_value=httpx.Response(201, json=SENT))

    with pytest.raises(WhatsAppError, match="empty"):
        await client.send_text(SENDER, "   ")

    assert not route.called


@respx.mock
async def test_a_send_that_returns_no_message_id_is_an_error(
    client: EvolutionWhatsAppClient,
) -> None:
    respx.post(SEND_TEXT_URL).mock(return_value=httpx.Response(201, json={"status": "PENDING"}))

    with pytest.raises(WhatsAppError, match="no message id"):
        await client.send_text(SENDER, "hi")


# --- retries and error hygiene ----------------------------------------------------------------


@respx.mock
async def test_a_server_error_is_retried_and_the_second_try_succeeds(
    client: EvolutionWhatsAppClient, caplog: pytest.LogCaptureFixture
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(201, json=SENT)]
    )

    with caplog.at_level(logging.WARNING):
        message_id = await client.send_text(SENDER, "hi")

    assert (message_id, route.call_count) == ("3EB0SENT", 2)
    assert "evolution_retry attempt=1" in caplog.text


@respx.mock
async def test_the_client_gives_up_after_its_attempts_and_the_error_hides_the_key(
    client: EvolutionWhatsAppClient,
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(return_value=httpx.Response(500, text=API_KEY))

    with pytest.raises(WhatsAppError, match="500") as raised:
        await client.send_text(SENDER, "hi")

    assert route.call_count == 3
    assert API_KEY not in str(raised.value)


@respx.mock
async def test_a_client_error_is_not_retried(client: EvolutionWhatsAppClient) -> None:
    route = respx.post(SEND_TEXT_URL).mock(return_value=httpx.Response(400, json={"error": "x"}))

    with pytest.raises(WhatsAppError, match="400"):
        await client.send_text(SENDER, "hi")

    assert route.call_count == 1


@respx.mock
async def test_a_connection_failure_is_retried_then_reported_without_the_url_or_key(
    client: EvolutionWhatsAppClient,
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(WhatsAppError, match="ConnectError") as raised:
        await client.send_text(SENDER, "hi")

    assert route.call_count == 3
    assert API_KEY not in str(raised.value) and BASE not in str(raised.value)


@respx.mock
@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ReadError("reset")])
async def test_a_send_that_may_already_have_been_delivered_is_not_retried(
    client: EvolutionWhatsAppClient, error: httpx.TransportError
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(side_effect=error)

    with pytest.raises(WhatsAppError, match=type(error).__name__):
        await client.send_text(SENDER, "hi")

    assert route.call_count == 1


@respx.mock
async def test_a_connect_timeout_on_a_send_is_retried_because_nothing_was_sent(
    client: EvolutionWhatsAppClient,
) -> None:
    route = respx.post(SEND_TEXT_URL).mock(side_effect=httpx.ConnectTimeout("no route"))

    with pytest.raises(WhatsAppError, match="ConnectTimeout"):
        await client.send_text(SENDER, "hi")

    assert route.call_count == 3


# --- voice ------------------------------------------------------------------------------------


async def test_upload_media_refuses_audio_over_the_cap(client: EvolutionWhatsAppClient) -> None:
    with pytest.raises(MediaTooLargeError):
        await client.upload_media(b"\0" * (MAX_MEDIA_BYTES + 1), "audio/ogg")


async def test_upload_media_accepts_audio_exactly_at_the_cap(
    client: EvolutionWhatsAppClient,
) -> None:
    media_id = await client.upload_media(b"\0" * MAX_MEDIA_BYTES, "audio/ogg")

    assert len(base64.b64decode(media_id)) == MAX_MEDIA_BYTES


async def test_upload_media_keeps_the_audio_as_its_own_base64_media_id(
    client: EvolutionWhatsAppClient,
) -> None:
    media_id = await client.upload_media(b"OggS-bytes", "audio/ogg; codecs=opus")

    assert base64.b64decode(media_id) == b"OggS-bytes"


@respx.mock
async def test_send_audio_posts_the_base64_as_a_voice_note_without_re_encoding(
    client: EvolutionWhatsAppClient,
) -> None:
    route = respx.post(SEND_AUDIO_URL).mock(return_value=httpx.Response(201, json=SENT))
    media_id = await client.upload_media(b"OggS-bytes", "audio/ogg; codecs=opus")

    message_id = await client.send_audio(SENDER, media_id)

    assert message_id == "3EB0SENT"
    request = route.calls.last.request
    assert request.headers["apikey"] == API_KEY
    assert _body(request) == {"number": SENDER, "audio": media_id, "encoding": False}


# --- inbound media ----------------------------------------------------------------------------


@respx.mock
async def test_download_media_asks_evolution_for_the_message_audio_and_decodes_it(
    client: EvolutionWhatsAppClient,
) -> None:
    audio = base64.b64encode(b"voice-bytes").decode()
    route = respx.post(MEDIA_URL).mock(
        return_value=httpx.Response(
            201, json={"base64": audio, "mimetype": "audio/ogg; codecs=opus", "mediaType": "audio"}
        )
    )

    media = await client.download_media("3EB0A1B2C3D4E5F6")

    assert media == DownloadedMedia(data=b"voice-bytes", mime_type="audio/ogg; codecs=opus")
    request = route.calls.last.request
    assert request.headers["apikey"] == API_KEY
    assert _body(request) == {"message": {"key": {"id": "3EB0A1B2C3D4E5F6"}}}


@respx.mock
async def test_a_download_that_times_out_reading_is_retried_because_it_changes_nothing(
    client: EvolutionWhatsAppClient,
) -> None:
    audio = base64.b64encode(b"voice-bytes").decode()
    route = respx.post(MEDIA_URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(201, json={"base64": audio})]
    )

    media = await client.download_media("3EB0A1B2C3D4E5F6")

    assert media.data == b"voice-bytes"
    assert route.call_count == 2


@respx.mock
async def test_download_media_refuses_audio_over_the_cap_before_decoding_it(
    client: EvolutionWhatsAppClient,
) -> None:
    too_big = "A" * ((MAX_MEDIA_BYTES // 3 + 2) * 4)
    respx.post(MEDIA_URL).mock(
        return_value=httpx.Response(201, json={"base64": too_big, "mimetype": "audio/ogg"})
    )

    with pytest.raises(MediaTooLargeError):
        await client.download_media("3EB0A1B2C3D4E5F6")


@pytest.mark.parametrize(
    "payload",
    [{}, {"base64": ""}, {"base64": 5}, {"base64": "***not base64***", "mimetype": "audio/ogg"}],
)
@respx.mock
async def test_download_media_reports_a_missing_or_corrupt_body(
    client: EvolutionWhatsAppClient, payload: dict
) -> None:
    respx.post(MEDIA_URL).mock(return_value=httpx.Response(201, json=payload))

    with pytest.raises(WhatsAppError):
        await client.download_media("3EB0A1B2C3D4E5F6")


@respx.mock
async def test_download_media_reports_a_message_evolution_does_not_have(
    client: EvolutionWhatsAppClient,
) -> None:
    respx.post(MEDIA_URL).mock(return_value=httpx.Response(404, json={"error": "not found"}))

    with pytest.raises(WhatsAppError, match="404"):
        await client.download_media("3EB0A1B2C3D4E5F6")


@respx.mock
async def test_a_download_with_no_mimetype_falls_back_to_ogg_opus(
    client: EvolutionWhatsAppClient,
) -> None:
    audio = base64.b64encode(b"voice").decode()
    respx.post(MEDIA_URL).mock(return_value=httpx.Response(201, json={"base64": audio}))

    media = await client.download_media("3EB0A1B2C3D4E5F6")

    assert media.mime_type.startswith("audio/ogg")


# --- unsupported ------------------------------------------------------------------------------


async def test_template_messages_are_unsupported_because_there_is_no_24_hour_window(
    client: EvolutionWhatsAppClient,
) -> None:
    with pytest.raises(WhatsAppError, match="not supported"):
        await client.send_template(SENDER, "daily_nudge", "en")
