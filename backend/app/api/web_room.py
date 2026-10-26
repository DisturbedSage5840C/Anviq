"""POST /web/turn: the browser demo of the coach, for people who are not on the WhatsApp test list.

The body is the turn itself: a recording (audio/*) or a typed line (text/plain), with the demo
code in X-Demo-Code. The declared Content-Type is the media allow-list. Replies are JSON with
the text and a base64 WAV the page can play. Same brain, same privacy rules as WhatsApp.

Order matters: everything that can be refused for free (code shape, media type, size, text) is
refused before a turn is spent, and a turn that was refused before any paid work ran is given back.
"""

import asyncio
import base64
import logging
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.deps import get_demo_codes, get_inbound_guard, get_web_turn
from app.web.demo_codes import CODE_PATTERN
from app.web.turn import WebReply, WebTurn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web")

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 2000
MAX_UTF8_BYTES_PER_CHAR = 4
MAX_TEXT_BYTES = MAX_TEXT_CHARS * MAX_UTF8_BYTES_PER_CHAR
# A recording of the longest allowed note arrives in a second or two; slower is a stalled client.
BODY_TIMEOUT_S = 10.0
TEXT_MIME = "text/plain"
AUDIO_MIMES = frozenset({"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav"})
REPLY_AUDIO_MIME = "audio/wav"
UTF8_CHARSETS = frozenset({"utf-8", "utf8"})

HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_REQUEST_TIMEOUT = 408
HTTP_PAYLOAD_TOO_LARGE = 413
HTTP_UNSUPPORTED_MEDIA = 415
HTTP_TOO_MANY_REQUESTS = 429

NO_STORE = {"Cache-Control": "no-store"}

# One message for a missing, malformed, wrong, expired or used-up code: never confirms a guess.
CODE_REFUSED = "That demo code does not work. Ask the team for a new one."


class WebTurnResponse(BaseModel):
    text: str
    lang: str
    audio_base64: str | None
    audio_mime: str | None
    refused: bool


class DemoCodes(Protocol):
    async def claim(self, code: str) -> str | None: ...

    async def refund(self, code: str) -> None: ...


class SenderLimiter(Protocol):
    async def allow_sender(self, sender_key: str) -> bool: ...


@router.post(
    "/turn",
    responses={
        400: {"description": "Empty body, text that is not UTF-8, or only whitespace"},
        401: {"description": "Missing, wrong, expired or used-up demo code"},
        408: {"description": "The body took too long to arrive"},
        413: {"description": "Body or text too long"},
        415: {"description": "Not audio/webm, audio/ogg, audio/mp4, audio/wav or text/plain"},
        429: {"description": "Too many turns for this code in the last hour"},
    },
)
async def web_turn(
    request: Request,
    response: Response,
    codes: Annotated[DemoCodes, Depends(get_demo_codes)],
    limiter: Annotated[SenderLimiter, Depends(get_inbound_guard)],
    turn: Annotated[WebTurn, Depends(get_web_turn)],
    x_demo_code: Annotated[str | None, Header()] = None,
) -> WebTurnResponse:
    response.headers.update(NO_STORE)
    code = _well_formed(x_demo_code)
    mime = _declared_mime(request)
    body = await _read_body(request, limit=MAX_TEXT_BYTES if mime == TEXT_MIME else MAX_BODY_BYTES)
    text = _typed_text(body) if mime == TEXT_MIME else None
    visitor = await codes.claim(code)
    if visitor is None:
        raise _error(HTTP_UNAUTHORIZED, CODE_REFUSED)
    try:
        reply = await _serve(limiter, turn, visitor, body, text, mime)
    except Exception:
        await _give_back(codes, code)
        raise
    if reply.free:
        await _give_back(codes, code)
    return _to_response(reply)


async def _serve(
    limiter: SenderLimiter, turn: WebTurn, visitor: str, body: bytes, text: str | None, mime: str
) -> WebReply:
    if not await limiter.allow_sender(visitor):
        raise _error(HTTP_TOO_MANY_REQUESTS, "Too many turns. Try again later.")
    if text is None:
        return await turn.respond_to_audio(visitor, body, mime)
    return await turn.respond_to_text(visitor, text)


async def _give_back(codes: DemoCodes, code: str) -> None:
    """Refund the claimed turn. Never raises: the caller is already handling the real outcome."""
    try:
        await codes.refund(code)
    except Exception:
        logger.error("could not refund a web turn", exc_info=True)


def _well_formed(code: str | None) -> str:
    if code is None or CODE_PATTERN.fullmatch(code) is None:
        raise _error(HTTP_UNAUTHORIZED, CODE_REFUSED)
    return code


def _declared_mime(request: Request) -> str:
    media_type, *params = (
        part.strip() for part in request.headers.get("content-type", "").split(";")
    )
    mime = media_type.lower()
    if mime != TEXT_MIME and mime not in AUDIO_MIMES:
        raise _error(
            HTTP_UNSUPPORTED_MEDIA,
            "Send audio/webm, audio/ogg, audio/mp4, audio/wav or text/plain.",
        )
    if mime == TEXT_MIME and not _is_utf8(params):
        raise _error(HTTP_UNSUPPORTED_MEDIA, "Text must be UTF-8.")
    return mime


def _is_utf8(params: list[str]) -> bool:
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() == "charset" and value.strip(' "').lower() not in UTF8_CHARSETS:
            return False
    return True


async def _read_body(request: Request, *, limit: int) -> bytes:
    """The whole body, refusing to buffer more than `limit` (even chunked) or to wait forever."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large()
    try:
        async with asyncio.timeout(BODY_TIMEOUT_S):
            return await _collect(request, limit)
    except TimeoutError:
        raise _error(HTTP_REQUEST_TIMEOUT, "That took too long to send. Try again.") from None


async def _collect(request: Request, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _too_large()
        chunks.append(chunk)
    if size == 0:
        raise _error(HTTP_BAD_REQUEST, "Nothing was sent.")
    return b"".join(chunks)


def _typed_text(body: bytes) -> str:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(HTTP_BAD_REQUEST, "Text must be UTF-8.") from None
    if len(text) > MAX_TEXT_CHARS:
        raise _too_large()
    if not text.strip():
        raise _error(HTTP_BAD_REQUEST, "Nothing was sent.")
    return text


def _too_large() -> HTTPException:
    return _error(HTTP_PAYLOAD_TOO_LARGE, "That is too long. Try something shorter.")


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status, detail, headers=NO_STORE)


def _to_response(reply: WebReply) -> WebTurnResponse:
    audio = base64.b64encode(reply.audio_wav).decode() if reply.audio_wav else None
    return WebTurnResponse(
        text=reply.text,
        lang=reply.lang,
        audio_base64=audio,
        audio_mime=REPLY_AUDIO_MIME if audio else None,
        refused=reply.refused,
    )
