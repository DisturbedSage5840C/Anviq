import base64
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.channel import twilio_client
from app.channel.twilio_client import (
    MAX_BODY_CHARS,
    TwilioWhatsAppClient,
    split_for_whatsapp,
)
from app.channel.whatsapp_client import MAX_MEDIA_BYTES, MediaTooLargeError, WhatsAppError

BASE = "https://twilio.test"
SID = "AC00000000000000000000000000000000"
TOKEN = "super-secret-auth-token"
FROM = "+14155238886"
MESSAGES_URL = f"{BASE}/2010-04-01/Accounts/{SID}/Messages.json"
MEDIA_URL = f"{BASE}/2010-04-01/Accounts/{SID}/Messages/MM1/Media/ME1"
CDN_URL = "https://media.twiliocdn.com/ME1"
BASIC = "Basic " + base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as http:
        yield TwilioWhatsAppClient(
            http,
            account_sid=SID,
            auth_token=TOKEN,
            from_number=FROM,
            base_url=BASE,
            retry_delay_s=0,
            chunk_delay_s=0,
        )


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


# --- splitting --------------------------------------------------------------------------------


def test_short_text_is_one_chunk() -> None:
    assert split_for_whatsapp("नमस्ते") == ["नमस्ते"]


def test_blank_text_has_no_chunks() -> None:
    assert split_for_whatsapp("  \n ") == []


def test_long_text_is_split_into_chunks_within_the_limit_without_losing_words() -> None:
    text = " ".join(f"शब्द{i}" for i in range(1200))

    chunks = split_for_whatsapp(text)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= MAX_BODY_CHARS for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_a_split_prefers_a_line_break_over_a_word_break() -> None:
    first, second = "a" * 1000, "b" * 1000

    assert split_for_whatsapp(f"{first}\n{second}") == [first, second]


def test_text_with_no_break_point_is_cut_at_the_limit() -> None:
    chunks = split_for_whatsapp("x" * (MAX_BODY_CHARS * 2 + 5))

    assert [len(c) for c in chunks] == [MAX_BODY_CHARS, MAX_BODY_CHARS, 5]


# --- sending ----------------------------------------------------------------------------------


@respx.mock
async def test_send_text_posts_the_whatsapp_form_with_basic_auth_and_returns_the_sid(
    client,
) -> None:
    route = respx.post(MESSAGES_URL).respond(201, json={"sid": "SMout"})

    sid = await client.send_text("919800000001", "नमस्ते")

    assert sid == "SMout"
    request = route.calls.last.request
    assert request.headers["Authorization"] == BASIC
    assert _form(request) == {
        "From": f"whatsapp:{FROM}",
        "To": "whatsapp:+919800000001",
        "Body": "नमस्ते",
    }


@respx.mock
async def test_a_long_reply_goes_out_as_several_messages_in_order(client) -> None:
    route = respx.post(MESSAGES_URL).mock(
        side_effect=[
            httpx.Response(201, json={"sid": "SM1"}),
            httpx.Response(201, json={"sid": "SM2"}),
        ]
    )
    text = "a" * MAX_BODY_CHARS + " " + "b" * 10

    sid = await client.send_text("919800000001", text)

    assert sid == "SM1"
    bodies = [_form(call.request)["Body"] for call in route.calls]
    assert bodies == ["a" * MAX_BODY_CHARS, "b" * 10]


@respx.mock
async def test_chunks_are_spaced_to_respect_the_sandbox_rate_limit(monkeypatch) -> None:
    respx.post(MESSAGES_URL).respond(201, json={"sid": "SM"})
    pauses: list[float] = []

    async def record(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr(twilio_client.asyncio, "sleep", record)
    async with httpx.AsyncClient() as http:
        spaced = TwilioWhatsAppClient(
            http,
            account_sid=SID,
            auth_token=TOKEN,
            from_number=FROM,
            base_url=BASE,
            chunk_delay_s=3.0,
        )
        await spaced.send_text("919800000001", "a" * MAX_BODY_CHARS + " b")

    assert pauses == [3.0]


async def test_an_empty_reply_is_refused_before_any_request(client) -> None:
    with respx.mock:
        route = respx.post(MESSAGES_URL).respond(201, json={"sid": "SM"})

        with pytest.raises(WhatsAppError, match="empty"):
            await client.send_text("919800000001", "   ")

    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize("body", [{}, {"sid": None}, {"sid": 5}, []])
async def test_a_send_answered_without_a_sid_is_an_error(client, body) -> None:
    respx.post(MESSAGES_URL).respond(201, json=body)

    with pytest.raises(WhatsAppError, match="message sid"):
        await client.send_text("919800000001", "hi")


@respx.mock
async def test_a_temporary_failure_is_retried_until_it_succeeds(client) -> None:
    route = respx.post(MESSAGES_URL).mock(
        side_effect=[
            httpx.Response(429, json={"code": 20429}),
            httpx.Response(503),
            httpx.Response(201, json={"sid": "SMok"}),
        ]
    )

    assert await client.send_text("919800000001", "hi") == "SMok"
    assert route.call_count == 3


@respx.mock
async def test_a_client_error_is_not_retried_and_names_only_status_and_code(client) -> None:
    route = respx.post(MESSAGES_URL).respond(
        400, json={"code": 63015, "message": "To whatsapp:+919800000001 has not joined"}
    )

    with pytest.raises(WhatsAppError) as caught:
        await client.send_text("919800000001", "hi")

    assert route.call_count == 1
    message = str(caught.value)
    assert "400" in message and "63015" in message
    assert "919800000001" not in message and TOKEN not in message


@respx.mock
async def test_a_network_failure_ends_in_an_error_that_leaks_nothing(client) -> None:
    respx.post(MESSAGES_URL).mock(side_effect=httpx.ConnectError("boom to +919800000001"))

    with pytest.raises(WhatsAppError) as caught:
        await client.send_text("919800000001", "hi")

    assert "ConnectError" in str(caught.value)
    assert "919800000001" not in str(caught.value) and TOKEN not in str(caught.value)


async def test_voice_replies_and_templates_are_not_available_on_the_sandbox(client) -> None:
    with pytest.raises(WhatsAppError, match="not supported"):
        await client.send_audio("919800000001", "media")
    with pytest.raises(WhatsAppError, match="not supported"):
        await client.upload_media(b"ogg", "audio/ogg")
    with pytest.raises(WhatsAppError, match="not supported"):
        await client.send_template("919800000001", "daily_plan_reminder_hi", "hi")


# --- downloading media ------------------------------------------------------------------------


@respx.mock
async def test_download_fetches_the_media_url_with_basic_auth(client) -> None:
    route = respx.get(MEDIA_URL).respond(
        200, content=b"OggS", headers={"Content-Type": "audio/ogg"}
    )

    media = await client.download_media(MEDIA_URL)

    assert (media.data, media.mime_type) == (b"OggS", "audio/ogg")
    assert route.calls.last.request.headers["Authorization"] == BASIC


@respx.mock
async def test_a_redirect_is_followed_without_sending_the_credentials_along(client) -> None:
    first = respx.get(MEDIA_URL).respond(307, headers={"Location": CDN_URL})
    second = respx.get(CDN_URL).respond(200, content=b"OggS", headers={"Content-Type": "audio/ogg"})

    media = await client.download_media(MEDIA_URL)

    assert media.data == b"OggS"
    assert first.calls.last.request.headers["Authorization"] == BASIC
    assert "Authorization" not in second.calls.last.request.headers


@respx.mock
@pytest.mark.parametrize(
    "target",
    [
        "http://media.twiliocdn.com/ME1",
        "https://media.cdn.example/ME1",
        "https://127.0.0.1/ME1",
        "https://[::1]/ME1",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/ME1",
        "https://intranet/ME1",
        "https://media.twiliocdn.com:8443/ME1",
        "https://twiliocdn.com.evil.example/ME1",
    ],
)
async def test_a_redirect_to_an_unsafe_place_is_refused(client, target: str) -> None:
    respx.get(MEDIA_URL).respond(302, headers={"Location": target})
    sink = respx.route().respond(200, content=b"secret")

    with pytest.raises(WhatsAppError, match="redirect"):
        await client.download_media(MEDIA_URL)

    assert sink.call_count == 0


@respx.mock
async def test_a_redirect_loop_is_cut_off(client) -> None:
    respx.get(MEDIA_URL).respond(302, headers={"Location": MEDIA_URL})

    with pytest.raises(WhatsAppError, match="redirect"):
        await client.download_media(MEDIA_URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://twilio.test/2010-04-01/Accounts/AC/Messages/MM/Media/ME",
        "https://evil.example/2010-04-01/Accounts/AC/Messages/MM/Media/ME",
        "https://twilio.test@evil.example/x",
        "https://twilio.test:8443/x",
        "file:///etc/passwd",
        "ME1",
        "",
    ],
)
async def test_a_media_url_that_is_not_ours_is_refused_before_any_request(client, url) -> None:
    with respx.mock:
        sink = respx.route().respond(200, content=b"x")

        with pytest.raises(WhatsAppError, match="media URL"):
            await client.download_media(url)

    assert sink.call_count == 0


@respx.mock
async def test_media_over_the_cap_is_refused_by_its_declared_length(client) -> None:
    respx.get(MEDIA_URL).respond(
        200, content=b"x", headers={"Content-Length": str(MAX_MEDIA_BYTES + 1)}
    )

    with pytest.raises(MediaTooLargeError):
        await client.download_media(MEDIA_URL)


@respx.mock
async def test_media_over_the_cap_is_refused_while_streaming(client) -> None:
    respx.get(MEDIA_URL).respond(200, content=b"x" * (MAX_MEDIA_BYTES + 1))

    with pytest.raises(MediaTooLargeError):
        await client.download_media(MEDIA_URL)


@respx.mock
async def test_a_missing_media_file_is_an_error_without_the_url(client) -> None:
    respx.get(MEDIA_URL).respond(404)

    with pytest.raises(WhatsAppError) as caught:
        await client.download_media(MEDIA_URL)

    assert "404" in str(caught.value) and "ME1" not in str(caught.value)


@respx.mock
async def test_a_temporary_download_failure_is_retried(client) -> None:
    route = respx.get(MEDIA_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=b"OggS")]
    )

    media = await client.download_media(MEDIA_URL)

    assert media.data == b"OggS" and route.call_count == 2


# --- review fixes -----------------------------------------------------------------------------


@respx.mock
async def test_a_later_chunk_failing_keeps_the_first_sid_so_a_job_retry_cannot_resend_chunk_one(
    client, caplog
) -> None:
    respx.post(MESSAGES_URL).mock(
        side_effect=[
            httpx.Response(201, json={"sid": "SM1"}),
            httpx.Response(400, json={"code": 63016}),
        ]
    )
    text = "private reply " + "a" * MAX_BODY_CHARS

    with caplog.at_level("WARNING"):
        sid = await client.send_text("919800000001", text)

    assert sid == "SM1"
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "chunk 2 of 2" in logged and "private reply" not in logged


@respx.mock
async def test_the_first_chunk_failing_still_raises(client) -> None:
    respx.post(MESSAGES_URL).respond(400, json={"code": 63016})

    with pytest.raises(WhatsAppError):
        await client.send_text("919800000001", "hello")


@respx.mock
async def test_a_malformed_redirect_location_is_a_clean_error(client) -> None:
    respx.get(MEDIA_URL).respond(302, headers={"Location": "http://[::1"})

    with pytest.raises(WhatsAppError):
        await client.download_media(MEDIA_URL)


@respx.mock
async def test_a_not_modified_answer_is_not_mistaken_for_media(client) -> None:
    respx.get(MEDIA_URL).respond(304)

    with pytest.raises(WhatsAppError, match="304"):
        await client.download_media(MEDIA_URL)


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/2010-04-01/Accounts/ACother/Messages/MM1/Media/ME1",
        f"{BASE}/2010-04-01/Accounts/{SID}.json",
        f"{BASE}/other/path",
    ],
)
@respx.mock
async def test_only_this_accounts_media_path_gets_the_credentials(client, url: str) -> None:
    sink = respx.route().respond(200, content=b"x")

    with pytest.raises(WhatsAppError, match="not on the Twilio API host"):
        await client.download_media(url)

    assert sink.call_count == 0
