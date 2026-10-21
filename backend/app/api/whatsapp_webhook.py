"""WhatsApp Cloud API webhook: handshake (GET) and signed event delivery (POST)."""

import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.api.admission import QueueUnavailableError, admit
from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue
from app.channel.messages import failed_delivery_codes, parse_inbound
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
    _require_meta_provider(settings)
    expected = settings.wa_verify_token.get_secret_value().encode()
    presented_ok = token is not None and hmac.compare_digest(token.encode(), expected)
    if mode != SUBSCRIBE_MODE or not presented_ok:
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
    _require_meta_provider(settings)
    body = await request.body()
    if not is_valid_signature(body, signature, settings.wa_app_secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    for code in failed_delivery_codes(payload):
        logger.warning("whatsapp delivery failed: code=%d", code)
    queued = 0
    try:
        for message in parse_inbound(payload):
            queued += await admit(message, settings, guard, queue)
    except QueueUnavailableError as exc:
        # Meta redelivers on a 5xx, and admit released the dedupe claim so the retry gets through.
        raise HTTPException(status_code=503, detail="queue unavailable") from exc
    # Never log message content or sender ids.
    logger.info("whatsapp webhook accepted", extra={"bytes": len(body), "queued": queued})
    return {"status": "received"}


def _require_meta_provider(settings: Settings) -> None:
    """Under Twilio this route stays dark: a guessable app secret must not open a second door."""
    if settings.whatsapp_provider != "meta":
        raise HTTPException(status_code=404, detail="not found")
