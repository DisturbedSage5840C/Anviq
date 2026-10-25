"""Evolution API webhook: one JSON POST per WhatsApp event, authenticated by a shared secret."""

import hmac
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.admission import QueueUnavailableError, admit
from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.evolution_messages import parse_evolution_inbound
from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/evolution")

# A text or voice-note event is a couple of KB (media travels separately, fetched on demand), so
# anything near this size is not an ordinary event.
MAX_BODY_BYTES = 256 * 1024


@router.post("")
async def receive_evolution_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    guard: Annotated[InboundGuard, Depends(get_inbound_guard)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    secret: Annotated[str | None, Header(alias="X-Anviq-Webhook-Secret")] = None,
) -> dict[str, int]:
    expected = _expected_secret(settings)
    # Checked before the body is read, so an unauthenticated caller cannot make us buffer it.
    if not _secret_matches(secret, expected):
        logger.warning("evolution webhook rejected: bad secret")
        raise HTTPException(status_code=401, detail="invalid secret")

    body = await _bounded_body(request)
    payload = _json_payload(body)
    message = parse_evolution_inbound(payload, now=int(time.time()))
    try:
        queued = await admit(message, settings, guard, queue) if message is not None else 0
    except QueueUnavailableError:
        # Evolution redelivers after a 5xx; admit released the dedupe claim, so the retry is queued.
        raise HTTPException(status_code=503, detail="queue unavailable") from None
    # Never log message content, sender ids or the secret.
    logger.info("evolution webhook accepted", extra={"bytes": len(body), "queued": queued})
    return {"queued": queued}


def _expected_secret(settings: Settings) -> str:
    """The shared secret, or 404 when this deploy is not on Evolution."""
    secret = settings.evolution_webhook_secret
    if settings.whatsapp_provider != "evolution" or secret is None:
        raise HTTPException(status_code=404, detail="not found")
    return secret.get_secret_value()


def _secret_matches(received: str | None, expected: str) -> bool:
    if not received:
        return False
    # Bytes, because compare_digest refuses a non-ASCII str.
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


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


def _json_payload(body: bytes) -> object:
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        # RecursionError: a deeply nested "[[[[..." fits well inside the size cap.
        raise HTTPException(status_code=400, detail="invalid json") from None
