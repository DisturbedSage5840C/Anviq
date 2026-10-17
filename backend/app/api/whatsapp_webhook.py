"""WhatsApp Cloud API webhook: handshake (GET) and signed event delivery (POST)."""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue
from app.channel.messages import InboundMessage, parse_inbound
from app.channel.sender_key import sender_key
from app.channel.signature import is_valid_signature
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/whatsapp")

SUBSCRIBE_MODE = "subscribe"


@router.get("")
async def verify_webhook(
    settings: Annotated[Settings, Depends(get_settings)],
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    if mode != SUBSCRIBE_MODE or token != settings.wa_verify_token.get_secret_value():
        raise HTTPException(status_code=403, detail="verification failed")
    return Response(content=challenge or "", media_type="text/plain")


@router.post("")
async def receive_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    guard: Annotated[InboundGuard, Depends(get_inbound_guard)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, str]:
    body = await request.body()
    if not is_valid_signature(body, signature, settings.wa_app_secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    queued = 0
    for message in parse_inbound(payload):
        queued += await _admit(message, settings, guard, queue)
    # Never log message content or sender ids.
    logger.info("whatsapp webhook accepted", extra={"bytes": len(body), "queued": queued})
    return {"status": "received"}


async def _admit(
    message: InboundMessage, settings: Settings, guard: InboundGuard, queue: JobQueue
) -> int:
    """Queue one message unless it is a redelivery or its sender is over the limit.

    Returns 1 if queued. Dropped messages are still acked (200) so Meta stops retrying;
    a queue failure is a 503 so Meta retries and the released dedupe claim lets it through.
    """
    if not await guard.claim_message(message.wa_message_id):
        return 0
    if not await guard.allow_sender(sender_key(settings, message.sender_wa_id)):
        logger.warning("sender rate limited; message dropped")
        return 0
    try:
        await queue.enqueue(message.to_envelope(), job_id=message.wa_message_id)
    except Exception as exc:
        await guard.release_message(message.wa_message_id)
        logger.exception("failed to enqueue inbound message")
        raise HTTPException(status_code=503, detail="queue unavailable") from exc
    return 1
