"""POST /web/turn: a demo code, a short recording or a typed line, a reply the page can play."""

import asyncio
import base64
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import web_room
from app.api.deps import get_demo_codes, get_inbound_guard, get_web_turn
from app.api.web_room import MAX_BODY_BYTES, MAX_TEXT_CHARS, _read_body
from app.config import Settings
from app.main import create_app
from app.web.turn import WebReply

GOOD_CODE = "Abcdefghijklmnopqrstu_"  # 22 url-safe characters, the shape of a real code
IDENTITY = "web:abc"
WAV = b"RIFF-fake-wav"
ORIGIN = "https://anviq-demo.example.app"


class _Codes:
    def __init__(self) -> None:
        self.claims: list[str] = []
        self.refunds: list[str] = []

    async def claim(self, code: str) -> str | None:
        self.claims.append(code)
        return IDENTITY if code == GOOD_CODE else None

    async def refund(self, code: str) -> None:
        self.refunds.append(code)


class _Guard:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.keys: list[str] = []

    async def allow_sender(self, sender_key: str) -> bool:
        self.keys.append(sender_key)
        return self.allowed


class _Turn:
    def __init__(self) -> None:
        self.reply = WebReply("नमस्ते", "hi", WAV)
        self.error: Exception | None = None
        self.calls: list[tuple[str, str, object]] = []

    async def respond_to_text(self, sender: str, text: str) -> WebReply:
        self.calls.append(("text", sender, text))
        return self._answer()

    async def respond_to_audio(self, sender: str, audio: bytes) -> WebReply:
        self.calls.append(("audio", sender, audio))
        return self._answer()

    def _answer(self) -> WebReply:
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def codes() -> _Codes:
    return _Codes()


@pytest.fixture
def guard() -> _Guard:
    return _Guard()


@pytest.fixture
def turn() -> _Turn:
    return _Turn()


@pytest.fixture
def client(codes: _Codes, guard: _Guard, turn: _Turn) -> Iterator[TestClient]:
    settings = Settings(wa_verify_token="v", wa_app_secret="s", _env_file=None)
    app = create_app(settings=settings, manage_resources=False, web_allowed_origins=[ORIGIN])
    app.dependency_overrides[get_demo_codes] = lambda: codes
    app.dependency_overrides[get_inbound_guard] = lambda: guard
    app.dependency_overrides[get_web_turn] = lambda: turn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _post(client: TestClient, *, code: str | None = GOOD_CODE, body=b"plan", mime="text/plain"):
    headers = {"Content-Type": mime}
    if code is not None:
        headers["X-Demo-Code"] = code
    return client.post("/web/turn", content=body, headers=headers)


def test_a_typed_turn_returns_the_reply_text_and_playable_audio(client, turn):
    response = _post(client, body="कल का प्लान".encode())

    assert response.status_code == 200
    assert response.json() == {
        "text": "नमस्ते",
        "lang": "hi",
        "audio_base64": base64.b64encode(WAV).decode(),
        "audio_mime": "audio/wav",
        "refused": False,
    }
    assert turn.calls == [("text", IDENTITY, "कल का प्लान")]


def test_a_recording_is_handed_over_as_raw_bytes(client, turn):
    response = _post(client, body=b"webm-bytes", mime="audio/webm;codecs=opus")

    assert response.status_code == 200
    assert turn.calls == [("audio", IDENTITY, b"webm-bytes")]


def test_a_reply_without_audio_has_null_audio_fields(client, turn):
    turn.reply = WebReply("ठीक है", "hi", None)

    body = _post(client).json()

    assert (body["audio_base64"], body["audio_mime"]) == (None, None)


def test_replies_are_never_cached(client):
    assert _post(client).headers["cache-control"] == "no-store"


@pytest.mark.parametrize("code", [None, "", "wrong-code", "x" * 500])
def test_a_missing_or_wrong_code_is_refused_without_running_the_turn(client, turn, code):
    response = _post(client, code=code)

    assert response.status_code == 401
    assert turn.calls == []


def test_a_malformed_code_gets_the_same_refusal_as_a_wrong_one(client):
    wrong = _post(client, code="Z" * 22).json()
    missing = _post(client, code=None).json()

    assert wrong == missing


def test_a_busy_code_is_rate_limited_by_an_opaque_key_not_the_code(client, guard, turn):
    guard.allowed = False

    response = _post(client)

    assert response.status_code == 429
    assert turn.calls == []
    assert guard.keys == [IDENTITY]
    assert GOOD_CODE not in guard.keys[0]


def test_unsupported_media_types_are_refused(client, turn):
    response = _post(client, body=b"<html>", mime="text/html")

    assert response.status_code == 415
    assert turn.calls == []


@pytest.mark.parametrize("mime", ["audio/webm", "audio/ogg", "audio/mp4", "audio/wav"])
def test_browser_recording_formats_are_accepted(client, mime):
    assert _post(client, body=b"x", mime=mime).status_code == 200


def test_an_oversized_recording_is_refused_before_the_turn_runs(client, turn):
    response = _post(client, body=b"x" * (MAX_BODY_BYTES + 1), mime="audio/webm")

    assert response.status_code == 413
    assert turn.calls == []


def test_an_oversized_chunked_body_is_refused_too(client, turn):
    def chunks() -> Iterator[bytes]:
        for _ in range(MAX_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    response = client.post(
        "/web/turn",
        content=chunks(),
        headers={"X-Demo-Code": GOOD_CODE, "Content-Type": "audio/webm"},
    )

    assert response.status_code == 413
    assert turn.calls == []


def test_over_long_text_and_empty_bodies_are_refused(client, turn):
    too_long = _post(client, body=("क" * (MAX_TEXT_CHARS + 1)).encode())
    empty = _post(client, body=b"")

    assert (too_long.status_code, empty.status_code) == (413, 400)
    assert turn.calls == []


def test_text_that_is_not_utf8_is_a_bad_request(client, turn):
    assert _post(client, body=b"\xff\xfe\x00").status_code == 400


def test_the_demo_page_origin_may_call_the_api_and_others_may_not(client):
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-demo-code,content-type",
    }

    allowed = client.options("/web/turn", headers={"Origin": ORIGIN, **preflight})
    other = client.options("/web/turn", headers={"Origin": "https://evil.example", **preflight})

    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert "x-demo-code" in allowed.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in other.headers


def test_a_code_of_the_wrong_shape_never_reaches_the_database(client, codes):
    _post(client, code="short")
    _post(client, code="x" * 500)
    _post(client, code=None)

    assert codes.claims == []


def test_requests_refused_before_the_claim_never_spend_a_turn(client, codes):
    _post(client, body=b"x" * (MAX_BODY_BYTES + 1), mime="audio/webm")
    _post(client, body=b"", mime="audio/webm")
    _post(client, body=b"<html>", mime="text/html")
    _post(client, body=b"\xff\xfe")
    _post(client, body=b"  \n ")

    assert codes.claims == []


def test_whitespace_only_text_is_a_bad_request(client):
    assert _post(client, body=b"  \n ").status_code == 400


def test_text_declared_in_another_charset_is_refused(client):
    response = _post(client, body=b"plan", mime="text/plain; charset=latin-1")

    assert response.status_code == 415


def test_text_declared_as_utf8_is_accepted(client):
    assert _post(client, mime="text/plain; charset=UTF-8").status_code == 200


def test_a_rate_limited_turn_gives_the_turn_back(client, codes, guard):
    guard.allowed = False

    _post(client)

    assert codes.refunds == [GOOD_CODE]


def test_a_turn_that_fails_gives_the_turn_back_and_still_fails(client, codes, turn):
    turn.error = RuntimeError("brain down")

    with pytest.raises(RuntimeError):
        _post(client)

    assert codes.refunds == [GOOD_CODE]


def test_a_refusal_the_coach_could_not_help_with_gives_the_turn_back(client, codes, turn):
    turn.reply = WebReply("आवाज़ साफ़ नहीं आई", "hi", None, refused=True)

    body = _post(client).json()

    assert (body["refused"], codes.refunds) == (True, [GOOD_CODE])


def test_a_served_turn_is_not_refunded(client, codes):
    _post(client)

    assert codes.refunds == []


@pytest.mark.parametrize(
    "send",
    [
        lambda c: _post(c, code=None),
        lambda c: _post(c, body=b"", mime="audio/webm"),
        lambda c: _post(c, body=b"<html>", mime="text/html"),
    ],
)
def test_error_responses_are_never_cached_either(client, send):
    response = send(client)

    assert response.status_code >= 400
    assert response.headers["cache-control"] == "no-store"


class _FakeRequest:
    """Just enough of a Request to drive the body reader."""

    def __init__(self, chunks, delay: float = 0.0) -> None:
        self.headers: dict[str, str] = {}
        self.consumed = 0
        self._chunks = chunks
        self._delay = delay

    async def stream(self):
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            self.consumed += 1
            yield chunk


async def test_the_body_reader_stops_buffering_at_its_limit():
    request = _FakeRequest([b"x" * 10] * 100)

    with pytest.raises(HTTPException) as refused:
        await _read_body(request, limit=25)

    assert (refused.value.status_code, request.consumed) == (413, 3)


async def test_a_client_that_trickles_its_body_is_cut_off(monkeypatch):
    monkeypatch.setattr(web_room, "BODY_TIMEOUT_S", 0.05)
    request = _FakeRequest([b"x"] * 100, delay=0.02)

    with pytest.raises(HTTPException) as refused:
        await _read_body(request, limit=1000)

    assert refused.value.status_code == 408
