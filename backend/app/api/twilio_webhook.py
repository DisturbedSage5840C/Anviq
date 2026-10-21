"""Twilio WhatsApp webhook: one signed form POST per inbound message."""

import logging
import time
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.api.admission import QueueUnavailableError, admit
from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue
from app.channel.twilio_messages import parse_twilio_inbound
from app.channel.twilio_signature import is_valid_twilio_signature
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/twilio")

# A WhatsApp message form is a few hundred bytes and about thirty fields; anything far past that
# is not Twilio, and the signature check would otherwise hash all of it.
MAX_BODY_BYTES = 64 * 1024
MAX_FORM_FIELDS = 100
# Twilio only needs a 2xx; an empty <Response/> means "send nothing back", since replies go out
# later through the REST API from the worker.
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'
# Static and XML-safe: the one case where the webhook itself answers the teacher.
RESEND_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?><Response><Message>'
    "Anviq could not take that message just now. Please send it again in a minute. "
    "अभी संदेश नहीं मिल सका। कृपया एक मिनट बाद फिर भेजें।"
    "</Message></Response>"
)


@router.post("")
async def receive_twilio_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    guard: Annotated[InboundGuard, Depends(get_inbound_guard)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    signature: Annotated[str | None, Header(alias="X-Twilio-Signature")] = None,
) -> Response:
    auth_token, public_url = _twilio_credentials(settings)
    body = await _bounded_body(request)
    params = _form_fields(body)
    if not is_valid_twilio_signature(auth_token, public_url, params, signature):
        logger.warning("twilio webhook rejected: bad signature")
        raise HTTPException(status_code=401, detail="invalid signature")

    message = parse_twilio_inbound(dict(params), now=int(time.time()))
    try:
        queued = await admit(message, settings, guard, queue) if message else 0
    except QueueUnavailableError:
        # Twilio does not redeliver after a 4xx/5xx, so a 503 would lose the message silently.
        # Tell the teacher instead; admit released the dedupe claim, so a resend gets through.
        return Response(content=RESEND_TWIML, media_type="application/xml")
    # Never log message content, sender ids or the auth token.
    logger.info("twilio webhook accepted", extra={"bytes": len(body), "queued": queued})
    return Response(content=EMPTY_TWIML, media_type="application/xml")


def _twilio_credentials(settings: Settings) -> tuple[str, str]:
    """The auth token and the exact URL Twilio signs, or 404 when this deploy is not on Twilio."""
    token, url = settings.twilio_auth_token, settings.twilio_webhook_url
    if settings.whatsapp_provider != "twilio" or token is None or url is None:
        raise HTTPException(status_code=404, detail="not found")
    return token.get_secret_value(), url


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="body too large")
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _form_fields(body: bytes) -> list[tuple[str, str]]:
    """Every field in order, repeats and blanks kept, because the signature covers them all."""
    try:
        return parse_qsl(
            body.decode("utf-8", errors="replace"),
            keep_blank_values=True,
            max_num_fields=MAX_FORM_FIELDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid form") from exc
